# pattern: test file
import json
import logging

from pipeline.json_logging import JsonFormatter, get_logger


class TestJsonFormatter:
    """AC6.1, AC6.2, AC6.3 — JSON formatting with required fields and contextual extras."""

    def test_ac61_output_is_valid_json(self):
        """AC6.1: Log output is valid JSON lines (one JSON object per line)."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test message",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)

        # Must be parseable as JSON
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_ac62_required_fields_present(self):
        """AC6.2: Each log entry includes timestamp, level, and message fields."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test message",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        parsed = json.loads(output)

        assert "timestamp" in parsed
        assert "level" in parsed
        assert "message" in parsed
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "test message"

    def test_ac62_timestamp_format_is_iso(self):
        """AC6.2: Timestamp is in ISO format."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="test.py",
            lineno=1,
            msg="warning message",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        parsed = json.loads(output)

        # ISO format like "2026-04-09T10:30:45.123456+00:00"
        # Can parse as ISO without error
        from datetime import datetime
        ts = datetime.fromisoformat(parsed["timestamp"])
        assert ts is not None

    def test_ac63_contextual_fields_included_when_provided(self):
        """AC6.3: Contextual fields (scan_root, source_path, delivery_id) present when available."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="message with context",
            args=(),
            exc_info=None,
        )
        # Set extra fields via record attributes
        record.scan_root = "/data/scan"
        record.source_path = "/data/scan/project/workplan/v1"
        record.delivery_id = "abc123def456"

        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["scan_root"] == "/data/scan"
        assert parsed["source_path"] == "/data/scan/project/workplan/v1"
        assert parsed["delivery_id"] == "abc123def456"

    def test_ac63_contextual_fields_absent_when_not_provided(self):
        """AC6.3: Contextual fields absent when not set."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="message without context",
            args=(),
            exc_info=None,
        )
        # Do NOT set extra fields

        output = formatter.format(record)
        parsed = json.loads(output)

        assert "scan_root" not in parsed
        assert "source_path" not in parsed
        assert "delivery_id" not in parsed

    def test_ac63_partial_contextual_fields(self):
        """AC6.3: Only provided contextual fields appear in output."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="partial context",
            args=(),
            exc_info=None,
        )
        # Set only scan_root and delivery_id
        record.scan_root = "/data"
        record.delivery_id = "xyz789"
        # Do NOT set source_path

        output = formatter.format(record)
        parsed = json.loads(output)

        assert "scan_root" in parsed
        assert "delivery_id" in parsed
        assert "source_path" not in parsed
        assert parsed["scan_root"] == "/data"
        assert parsed["delivery_id"] == "xyz789"

    def test_level_names_correctly_formatted(self):
        """Additional: Different log levels are formatted correctly."""
        formatter = JsonFormatter()

        for level_name, level_int in [
            ("DEBUG", logging.DEBUG),
            ("INFO", logging.INFO),
            ("WARNING", logging.WARNING),
            ("ERROR", logging.ERROR),
            ("CRITICAL", logging.CRITICAL),
        ]:
            record = logging.LogRecord(
                name="test",
                level=level_int,
                pathname="test.py",
                lineno=1,
                msg="test",
                args=(),
                exc_info=None,
            )
            output = formatter.format(record)
            parsed = json.loads(output)
            assert parsed["level"] == level_name


class TestGetLogger:
    """AC6.4 — Logger factory with file and stderr handlers."""

    def test_ac64_logs_to_stderr(self, capsys):
        """AC6.4: Logs written to stderr."""
        logger = get_logger("test_stderr")
        logger.info("test message")

        captured = capsys.readouterr()
        assert "test message" in captured.err
        # Verify it's valid JSON
        parsed = json.loads(captured.err.strip())
        assert parsed["message"] == "test message"

    def test_ac64_logs_to_file(self, tmp_path):
        """AC6.4: Logs written to file."""
        log_dir = tmp_path / "logs"
        log_file = log_dir / "crawler.log"

        logger = get_logger("test_file", log_dir=str(log_dir))
        logger.info("test message to file")

        assert log_file.exists()
        content = log_file.read_text()
        assert "test message to file" in content
        # Verify it's valid JSON
        parsed = json.loads(content.strip())
        assert parsed["message"] == "test message to file"

    def test_ac64_both_stderr_and_file(self, tmp_path, capsys):
        """AC6.4: Logs written to both file and stderr."""
        log_dir = tmp_path / "logs"
        log_file = log_dir / "crawler.log"

        logger = get_logger("test_both", log_dir=str(log_dir))
        logger.info("message to both")

        # Check stderr
        captured = capsys.readouterr()
        assert "message to both" in captured.err
        stderr_parsed = json.loads(captured.err.strip())
        assert stderr_parsed["message"] == "message to both"

        # Check file
        assert log_file.exists()
        file_content = log_file.read_text()
        assert "message to both" in file_content
        file_parsed = json.loads(file_content.strip())
        assert file_parsed["message"] == "message to both"

    def test_log_dir_created_if_missing(self, tmp_path):
        """Additional: log_dir is created if it doesn't exist."""
        log_dir = tmp_path / "new" / "nested" / "logs"
        assert not log_dir.exists()

        logger = get_logger("test_mkdir", log_dir=str(log_dir))
        logger.info("test")

        assert log_dir.exists()
        assert (log_dir / "crawler.log").exists()

    def test_custom_log_filename(self, tmp_path):
        """Additional: Custom log filename is respected."""
        log_dir = tmp_path / "logs"
        custom_filename = "my_custom.log"
        log_file = log_dir / custom_filename

        logger = get_logger("test_custom", log_dir=str(log_dir), log_filename=custom_filename)
        logger.info("custom file test")

        assert log_file.exists()
        content = log_file.read_text()
        assert "custom file test" in content

    def test_no_file_handler_when_log_dir_none(self, capsys):
        """Additional: No file handler created when log_dir is None."""
        logger = get_logger("test_no_file", log_dir=None)
        logger.info("only stderr")

        captured = capsys.readouterr()
        assert "only stderr" in captured.err

    def test_logger_level_respected(self, capsys):
        """Additional: Logger level is respected."""
        logger = get_logger("test_level", log_dir=None, level=logging.WARNING)
        logger.debug("debug message")
        logger.info("info message")
        logger.warning("warning message")

        captured = capsys.readouterr()
        assert "debug message" not in captured.err
        assert "info message" not in captured.err
        assert "warning message" in captured.err

    def test_no_duplicate_handlers_on_multiple_calls(self, capsys):
        """Additional: Multiple calls with same name don't duplicate handlers."""
        logger1 = get_logger("test_dup", log_dir=None)
        logger2 = get_logger("test_dup", log_dir=None)

        # Same object
        assert logger1 is logger2

        logger1.info("test message")
        captured = capsys.readouterr()

        # Count occurrences - should be one, not multiple
        message_count = captured.err.count("test message")
        assert message_count == 1

    def test_contextual_fields_via_extra_kwarg(self, tmp_path, capsys):
        """Additional: Extra contextual fields work via logging.info(..., extra={...})."""
        log_dir = tmp_path / "logs"
        logger = get_logger("test_extra", log_dir=str(log_dir))

        logger.info(
            "message with extra context",
            extra={
                "scan_root": "/scan",
                "delivery_id": "del123",
            },
        )

        captured = capsys.readouterr()
        parsed = json.loads(captured.err.strip())
        assert parsed["scan_root"] == "/scan"
        assert parsed["delivery_id"] == "del123"
