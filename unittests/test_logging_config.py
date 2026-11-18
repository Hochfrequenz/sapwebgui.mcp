"""Tests for logging configuration and structured formatter."""

import importlib.metadata as _md
import json
import logging
import os
from unittest.mock import patch

import pytest

from sapguimcp.logging_config import (
    COMMIT_UNKNOWN,
    BrowserLogContext,
    QueryLogContext,
    StructuredFormatter,
    ToolLogContext,
    TransactionLogContext,
    _BuildContextFilter,
    build_info,
    configure_logging,
)


class TestStructuredFormatter:
    """Tests for the dual-mode structured formatter."""

    def test_console_format_plain_message(self) -> None:
        """Plain message without extra fields uses simple format."""
        formatter = StructuredFormatter(json_mode=False)
        record = logging.LogRecord(
            name="sapguimcp.tools.sap_tools",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Server started",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        assert "INFO" in output
        assert "sapguimcp.tools.sap_tools" in output
        assert "Server started" in output

    def test_console_format_with_extra_fields(self) -> None:
        """Extra fields are appended as key=value pairs."""
        formatter = StructuredFormatter(json_mode=False)
        record = logging.LogRecord(
            name="sapguimcp.tools.sap_tools",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Tool completed",
            args=(),
            exc_info=None,
        )
        record.tool = "sap_login"
        record.duration_ms = 2340
        output = formatter.format(record)
        assert "Tool completed" in output
        assert "tool=sap_login" in output
        assert "duration_ms=2340" in output

    def test_json_format_plain_message(self) -> None:
        """JSON mode outputs valid JSON with standard fields."""
        formatter = StructuredFormatter(json_mode=True)
        record = logging.LogRecord(
            name="sapguimcp.server",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Server started",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["logger"] == "sapguimcp.server"
        assert data["msg"] == "Server started"
        assert "ts" in data

    def test_json_format_with_extra_fields(self) -> None:
        """Extra fields are included as top-level JSON keys."""
        formatter = StructuredFormatter(json_mode=True)
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="Slow query",
            args=(),
            exc_info=None,
        )
        record.table = "MARA"
        record.rows = 500
        output = formatter.format(record)
        data = json.loads(output)
        assert data["msg"] == "Slow query"
        assert data["table"] == "MARA"
        assert data["rows"] == 500

    def test_json_format_with_exception(self) -> None:
        """Exception info is included in JSON output."""
        formatter = StructuredFormatter(json_mode=True)
        try:
            raise ValueError("test error")
        except ValueError:
            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="",
                lineno=0,
                msg="Something broke",
                args=(),
                exc_info=True,
            )
            # LogRecord captures exc_info from sys.exc_info() when exc_info=True
            import sys

            record.exc_info = sys.exc_info()
        output = formatter.format(record)
        data = json.loads(output)
        assert data["msg"] == "Something broke"
        assert "exc" in data
        assert "ValueError" in data["exc"]

    def test_console_format_excludes_stdlib_attrs(self) -> None:
        """Standard LogRecord attributes are not repeated as extra fields."""
        formatter = StructuredFormatter(json_mode=False)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Hello",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        # Should not contain internal LogRecord fields like pathname, lineno, etc.
        assert "pathname=" not in output
        assert "lineno=" not in output

    def test_percent_formatting_resolved(self) -> None:
        """Messages with %-args are resolved before formatting."""
        formatter = StructuredFormatter(json_mode=True)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Loaded %d items from %s",
            args=(42, "catalog"),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["msg"] == "Loaded 42 items from catalog"

    def test_console_format_with_identity_fields(self) -> None:
        """SAP identity fields appear as key=value pairs in console mode."""
        formatter = StructuredFormatter(json_mode=False)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Tool completed",
            args=(),
            exc_info=None,
        )
        record.sap_user = "TESTUSER"
        record.sap_host = "sap-prod.acme.com"
        record.sap_mandant = "100"
        record.tool = "sap_transaction"
        output = formatter.format(record)
        assert "sap_user=TESTUSER" in output
        assert "sap_host=sap-prod.acme.com" in output
        assert "sap_mandant=100" in output
        assert "tool=sap_transaction" in output

    def test_json_format_with_identity_fields(self) -> None:
        """SAP identity fields appear as top-level JSON keys."""
        formatter = StructuredFormatter(json_mode=True)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Tool completed",
            args=(),
            exc_info=None,
        )
        record.sap_user = "TESTUSER"
        record.sap_host = "sap-prod.acme.com"
        record.sap_mandant = "100"
        output = formatter.format(record)
        data = json.loads(output)
        assert data["sap_user"] == "TESTUSER"
        assert data["sap_host"] == "sap-prod.acme.com"
        assert data["sap_mandant"] == "100"

    def test_identity_fields_not_present_pre_login(self) -> None:
        """Before login, identity fields should not appear in output."""
        formatter = StructuredFormatter(json_mode=True)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Tool completed",
            args=(),
            exc_info=None,
        )
        record.tool = "browser_snapshot"
        output = formatter.format(record)
        data = json.loads(output)
        assert "sap_user" not in data
        assert "sap_host" not in data
        assert "sap_mandant" not in data


class TestLogContextModels:
    """Tests for Pydantic log context models."""

    def test_tool_log_context_full(self) -> None:
        ctx = ToolLogContext(tool="sap_login", session="s1", duration_ms=2340)
        d = ctx.model_dump(mode="json", exclude_none=True)
        assert d == {"tool": "sap_login", "session": "s1", "duration_ms": 2340}

    def test_tool_log_context_minimal(self) -> None:
        ctx = ToolLogContext(tool="sap_login")
        d = ctx.model_dump(mode="json", exclude_none=True)
        assert d == {"tool": "sap_login"}

    def test_transaction_log_context(self) -> None:
        ctx = TransactionLogContext(tool="sap_transaction", tcode="VA01", session="s1")
        d = ctx.model_dump(mode="json", exclude_none=True)
        assert d == {"tool": "sap_transaction", "tcode": "VA01", "session": "s1"}

    def test_query_log_context(self) -> None:
        ctx = QueryLogContext(tool="sap_se16_query", table="MARA", rows=100, total_hits=500)
        d = ctx.model_dump(mode="json", exclude_none=True)
        assert d["table"] == "MARA"
        assert d["rows"] == 100
        assert d["total_hits"] == 500

    def test_browser_log_context(self) -> None:
        ctx = BrowserLogContext(tool="browser_click", selector="#btn1")
        d = ctx.model_dump(mode="json", exclude_none=True)
        assert d == {"tool": "browser_click", "selector": "#btn1"}

    def test_exclude_none_drops_empty_fields(self) -> None:
        ctx = ToolLogContext(tool="test", session=None, agent_id=None)
        d = ctx.model_dump(mode="json", exclude_none=True)
        assert "session" not in d
        assert "agent_id" not in d


class TestConfigureLogging:
    """Tests for the configure_logging function."""

    @pytest.fixture(autouse=True)
    def _restore_root_handlers(self) -> None:
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        original_level = root.level
        yield
        root.handlers = original_handlers
        root.level = original_level

    def test_configure_logging_default_console(self) -> None:
        """Default config uses console formatter."""
        configure_logging()
        root = logging.getLogger()
        assert any(isinstance(h.formatter, StructuredFormatter) for h in root.handlers)

    def test_configure_logging_json_mode(self) -> None:
        """log_format='json' uses JSON formatter."""
        configure_logging(log_format="json")
        root = logging.getLogger()
        structured_handlers = [h for h in root.handlers if isinstance(h.formatter, StructuredFormatter)]
        assert len(structured_handlers) > 0
        assert structured_handlers[0].formatter.json_mode is True

    def test_configure_logging_preserves_non_stream_handlers(self) -> None:
        """configure_logging does not remove non-StreamHandler handlers."""
        root = logging.getLogger()
        file_handler = logging.FileHandler(os.devnull)
        root.addHandler(file_handler)
        configure_logging()
        assert file_handler in root.handlers


class TestBuildInfo:
    """Tests for the package version + commit parser used in canonical events."""

    @pytest.mark.parametrize(
        "raw,want",
        [
            # Tagged release: no local segment.
            ("0.9.12", ("0.9.12", "unknown")),
            # hatch-vcs dev build with commit only.
            ("0.9.12.dev3+gabc1234", ("0.9.12.dev3", "abc1234")),
            # hatch-vcs dev + dirty: commit gets +dirty suffix.
            ("0.9.12.dev3+gabc1234.d20260408", ("0.9.12.dev3", "abc1234+dirty")),
            # Long SHA: truncated to 7 chars.
            ("1.0.0+gf41a95d34abcdef", ("1.0.0", "f41a95d")),
            # Local segment present but no g-prefix part: commit stays unknown.
            ("1.0.0+localmod", ("1.0.0", "unknown")),
            # Empty local segment: don't crash, commit stays unknown.
            ("1.0.0+", ("1.0.0", "unknown")),
            # Bare 'g' with no SHA after it: defended by len(part)>1 check,
            # commit stays unknown (regression guard for IndexError).
            ("1.0.0+g", ("1.0.0", "unknown")),
            # Bare 'd' with no date after it: same guard for the dirty marker.
            ("1.0.0+gabc1234.d", ("1.0.0", "abc1234")),
        ],
    )
    def test_build_info_parses_hatch_vcs_format(self, raw: str, want: tuple[str, str]) -> None:
        """build_info splits hatch-vcs version strings into (base, short-SHA[+dirty])."""
        with patch("sapguimcp.logging_config.importlib.metadata.version", return_value=raw):
            assert build_info() == want

    def test_build_info_falls_back_when_package_not_installed(self) -> None:
        """When the package isn't installed, build_info returns ('dev', 'unknown')."""
        with patch(
            "sapguimcp.logging_config.importlib.metadata.version",
            side_effect=_md.PackageNotFoundError("sapguimcp"),
        ):
            assert build_info() == ("dev", COMMIT_UNKNOWN)


class TestBuildContextFilter:
    """Tests for the logging filter that injects version+commit on every record."""

    def test_filter_sets_attributes_on_record(self) -> None:
        """filter() sets version and commit attrs on the record and returns True."""
        flt = _BuildContextFilter("v1.2.3", "abcdef0")
        record = logging.LogRecord("x", logging.INFO, "", 0, "msg", (), None)
        assert flt.filter(record) is True
        assert getattr(record, "version") == "v1.2.3"
        assert getattr(record, "commit") == "abcdef0"

    def test_configure_logging_attaches_filter_to_stream_handler(self) -> None:
        """The StreamHandler installed by configure_logging carries the build filter."""
        with patch("sapguimcp.logging_config.build_info", return_value=("v9.9.9", "deadbee")):
            configure_logging()
        stream_handlers = [
            h
            for h in logging.getLogger().handlers
            if type(h) is logging.StreamHandler  # pylint: disable=unidiomatic-typecheck
        ]
        assert stream_handlers, "expected exactly one StreamHandler after configure_logging"
        filters = [f for f in stream_handlers[0].filters if isinstance(f, _BuildContextFilter)]
        assert len(filters) == 1
        # Verify the filter was constructed with the patched values by triggering
        # filter() and reading the attrs it sets — avoids poking at private state.
        probe = logging.LogRecord("x", logging.INFO, "", 0, "msg", (), None)
        filters[0].filter(probe)
        assert getattr(probe, "version") == "v9.9.9"
        assert getattr(probe, "commit") == "deadbee"

    def test_filter_propagates_to_emitted_records(self) -> None:
        """Records emitted via a child logger reach the StreamHandler with version+commit set."""
        with patch("sapguimcp.logging_config.build_info", return_value=("v1.0.0", "1234567")):
            configure_logging(log_format="json")
        captured: list[logging.LogRecord] = []
        for h in logging.getLogger().handlers:
            if type(h) is logging.StreamHandler:  # pylint: disable=unidiomatic-typecheck
                h.addFilter(lambda r: captured.append(r) or True)
        logging.getLogger("sapguimcp.something.deep").info("hello")
        assert captured, "expected at least one record to reach the handler"
        assert getattr(captured[-1], "version", None) == "v1.0.0"
        assert getattr(captured[-1], "commit", None) == "1234567"
