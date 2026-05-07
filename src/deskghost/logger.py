import logging
import time

LOG_INTERVAL_SECONDS = 60

_FMT = "[%(asctime)s] [%(levelname)-5s] %(message)s"
_DATEFMT = "%H:%M:%S"


def get_logger(name: str = "deskghost") -> logging.Logger:
    """Return (and lazily configure) the shared application logger."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FMT, datefmt=_DATEFMT))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


class ThrottledLogger:
    """Wraps the shared logger and suppresses repeated messages.

    Calls ``logger.info`` only when at least *interval* seconds have
    elapsed since the last emission for the same *key*.
    """

    def __init__(self, interval: int = LOG_INTERVAL_SECONDS) -> None:
        self._interval = interval
        self._last: dict[str, float] = {}
        self._log = get_logger()

    def info(self, key: str, message: str) -> None:
        now = time.time()
        if now - self._last.get(key, 0) >= self._interval:
            self._log.info(message)
            self._last[key] = now
