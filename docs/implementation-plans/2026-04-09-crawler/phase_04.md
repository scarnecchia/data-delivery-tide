# Crawler Service Implementation Plan

**Goal:** Build the filesystem crawler intake layer for the healthcare data pipeline

**Architecture:** Functional Core / Imperative Shell. Pure functions handle parsing, fingerprinting, and manifest construction. Thin imperative shell handles filesystem I/O, manifest writing, and HTTP calls.

**Tech Stack:** Python 3.10+, stdlib only (no new runtime deps), pytest + httpx for testing

**Scope:** 5 phases from original design (phases 1-5)

**Codebase verified:** 2026-04-09

---

## Acceptance Criteria Coverage

This phase implements and tests:

### crawler.AC6: Structured JSON Logging
- **crawler.AC6.1 Success:** Log output is valid JSON lines (one JSON object per line)
- **crawler.AC6.2 Success:** Each log entry includes timestamp, level, and message fields
- **crawler.AC6.3 Success:** Contextual fields (scan_root, source_path, delivery_id) present when available
- **crawler.AC6.4 Success:** Logs written to both file (log_dir) and stderr

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->

<!-- START_TASK_1 -->
### Task 1: Create json_logging.py with JSON formatter and logger factory

**Verifies:** crawler.AC6.1, crawler.AC6.2, crawler.AC6.3, crawler.AC6.4

**Files:**
- Create: `src/pipeline/json_logging.py`
- Create: `tests/test_json_logging.py`

**Implementation:**

`json_logging.py` is Imperative Shell — it configures stdlib logging handlers which perform I/O. It provides a JSON formatter and a factory function to create loggers with both file and stderr output.

This is the project's first logging implementation. The module provides a custom `json.Formatter` that outputs one JSON object per line and a `get_logger()` factory that wires up file + stderr handlers.

```python
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
        for key in ("scan_root", "source_path", "delivery_id"):
            value = getattr(record, key, None)
            if value is not None:
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
```

**Testing:**

Tests must verify each AC listed above. Follow project conventions: class-based grouping.

- **crawler.AC6.1:** Call logger.info(), capture output, parse each line as JSON — must succeed without error
- **crawler.AC6.2:** Parse JSON output, assert "timestamp", "level", "message" keys all present with correct values
- **crawler.AC6.3:** Call logger.info("msg", extra={"scan_root": "/foo", "delivery_id": "abc"}), assert those keys appear in JSON output. Call without extras, assert those keys are absent.
- **crawler.AC6.4:** Create logger with a temp log_dir, emit a log message, assert message appears both in captured stderr and in the file on disk

Test approach: Use a `logging.Handler` subclass or `StringIO` stream to capture formatter output for assertions. For AC6.4 file handler test, use `tmp_path` fixture.

Test file structure:

```python
class TestJsonFormatter:
    # AC6.1, AC6.2, AC6.3

class TestGetLogger:
    # AC6.4, handler configuration
```

**Verification:**

Run: `uv run pytest tests/test_json_logging.py -v`
Expected: All tests pass

**Commit:** `feat(pipeline): add structured JSON logging`
<!-- END_TASK_1 -->

<!-- END_SUBCOMPONENT_A -->
