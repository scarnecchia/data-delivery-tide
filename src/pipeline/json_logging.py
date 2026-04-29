# pattern: Imperative Shell
import json
import logging
import os
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """Formats log records as JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        # Merge any extra contextual fields set via `extra=` kwarg
        standard_attrs = logging.LogRecord("", 0, "", 0, None, None, None).__dict__.keys()
        for key, value in record.__dict__.items():
            if key not in standard_attrs and value is not None:
                entry[key] = value
        return json.dumps(entry)


def get_logger(
    name: str,
    log_dir: str | None = None,
    log_filename: str = "crawler.log",
    level: int = logging.INFO,
) -> logging.Logger:
    """Create a logger with JSON formatting to both stderr and a log file.

    Args:
        name: Logger name (typically __name__ or "crawler")
        log_dir: Directory for log file. If None, file handler is skipped.
        log_filename: Name of the log file within log_dir
        level: Logging level

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers if called multiple times
    if logger.handlers:
        return logger

    formatter = JsonFormatter()

    # stderr handler
    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)

    # File handler (if log_dir provided)
    if log_dir is not None:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.FileHandler(
            os.path.join(log_dir, log_filename)
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
