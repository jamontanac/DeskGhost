import logging
import pathlib
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


def configure_file_logging(log_dir: pathlib.Path | None = None) -> pathlib.Path:
    """Add a FileHandler to the shared logger.

    Creates ``log_dir`` if it does not exist.  Defaults to
    ``~/.deskghost/logs/``.  Returns the path of the log file.

    Safe to call multiple times — a second call is a no-op if a
    FileHandler pointing to the same path is already attached.
    """
    if log_dir is None:
        log_dir = pathlib.Path.home() / ".deskghost" / "logs"

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "deskghost.log"

    logger = get_logger()
    # Avoid attaching a duplicate FileHandler if called more than once
    for h in logger.handlers:
        if isinstance(h, logging.FileHandler) and h.baseFilename == str(log_file):
            return log_file

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(_FMT, datefmt=_DATEFMT))
    logger.addHandler(file_handler)

    return log_file


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
