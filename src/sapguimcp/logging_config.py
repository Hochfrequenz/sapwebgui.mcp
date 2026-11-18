"""Structured logging configuration for SAP Web GUI MCP Server.

Provides a dual-mode formatter (human-readable console or JSON) and
Pydantic models for type-safe structured log context.

Usage:
    from sapguimcp.logging_config import configure_logging, ToolLogContext

    configure_logging()  # Call once at startup

    ctx = ToolLogContext(tool="sap_login", session="s1", duration_ms=2340)
    logger.info("Tool completed", extra=ctx.model_dump(mode="json", exclude_none=True))

LOG_FORMAT and LOG_LEVEL are read from SapGuiSettings (pydantic-settings).
"""

import importlib.metadata
import json
import logging
import traceback
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

__all__ = [
    "StructuredFormatter",
    "ToolLogContext",
    "TransactionLogContext",
    "QueryLogContext",
    "BrowserLogContext",
    "configure_logging",
    "build_info",
]

# Sentinel returned by build_info when no commit identifier can be derived
# from the installed package version (e.g. wheel built without VCS metadata,
# or running from a source tree without hatch-vcs).
COMMIT_UNKNOWN = "unknown"
VERSION_UNKNOWN = "dev"

# Standard LogRecord attributes to exclude from extra fields
_LOGRECORD_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
        "created",
        "relativeCreated",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "pathname",
        "filename",
        "module",
        "thread",
        "threadName",
        "process",
        "processName",
        "levelname",
        "levelno",
        "msecs",
        "message",
        "asctime",
        "taskName",
    }
)


class ToolLogContext(BaseModel):
    """Structured context for tool call log events."""

    tool: str
    session: str | None = None
    agent_id: str | None = None
    duration_ms: int | None = None
    error: str | None = None
    request_id: str | None = None


def build_info() -> tuple[str, str]:
    """Return (version, commit) for the installed sapguimcp package.

    The version string emitted by hatch-vcs has the shape
    ``<base>+g<sha>.d<date>`` for dev/dirty builds and just ``<base>`` for
    tagged releases. We split on the first ``+`` to recover the base
    version, then look for a ``g<sha>`` segment to recover the commit
    short-SHA. The presence of any ``d<date>`` segment marks the working
    tree as dirty.

    Falls back to ``("dev", "unknown")`` when the package isn't installed
    (e.g. running tests from a source tree without an editable install)
    or when the version string carries no local segment.
    """
    try:
        full = importlib.metadata.version("sapguimcp")
    except importlib.metadata.PackageNotFoundError:
        return (VERSION_UNKNOWN, COMMIT_UNKNOWN)
    if "+" not in full:
        return (full, COMMIT_UNKNOWN)
    base, local = full.split("+", 1)
    commit = COMMIT_UNKNOWN
    dirty = False
    for part in local.split("."):
        if part.startswith("g") and len(part) > 1:
            commit = part[1:]
            if len(commit) > 7:
                commit = commit[:7]
        elif part.startswith("d") and len(part) > 1:
            dirty = True
    if dirty and commit != COMMIT_UNKNOWN:
        commit += "+dirty"
    return (base, commit)


class _BuildContextFilter(logging.Filter):  # pylint: disable=too-few-public-methods
    """Inject build version+commit into every log record passing through.

    Attached to handlers (not loggers) in ``configure_logging`` so that
    records propagated up from child loggers also receive the fields —
    Python only runs logger-level filters for records emitted directly
    on that logger, while handler-level filters apply to everything the
    handler emits.
    """

    def __init__(self, version: str, commit: str) -> None:
        super().__init__()
        self._version = version
        self._commit = commit

    def filter(self, record: logging.LogRecord) -> bool:
        record.version = self._version
        record.commit = self._commit
        return True


class TransactionLogContext(ToolLogContext):
    """Structured context for SAP transaction log events."""

    tcode: str


class QueryLogContext(ToolLogContext):
    """Structured context for SE16 query log events."""

    table: str
    rows: int | None = None
    total_hits: int | None = None


class BrowserLogContext(ToolLogContext):
    """Structured context for browser interaction log events."""

    selector: str | None = None
    url: str | None = None


class StructuredFormatter(logging.Formatter):
    """Dual-mode formatter: human-readable console or JSON.

    Extra fields from the log record (set via ``extra={}``) are appended
    as ``key=value`` pairs in console mode or as top-level JSON keys in
    JSON mode.
    """

    def __init__(self, json_mode: bool = False) -> None:
        super().__init__()
        self.json_mode = json_mode

    def _extract_extra(self, record: logging.LogRecord) -> dict[str, Any]:
        """Extract non-standard fields from the log record."""
        extra: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in _LOGRECORD_ATTRS:
                continue
            extra[key] = value
        return extra

    def format(self, record: logging.LogRecord) -> str:
        # Resolve %-formatting
        record.message = record.getMessage()
        extra = self._extract_extra(record)
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

        if self.json_mode:
            return self._format_json(record, extra, ts)
        return self._format_console(record, extra, ts)

    def _format_console(self, record: logging.LogRecord, extra: dict[str, Any], ts: str) -> str:
        parts = [
            ts,
            f"{record.levelname:<5s}",
            record.name,
            "",
            record.message,
        ]
        if extra:
            kv = "  ".join(f"{k}={v}" for k, v in extra.items())
            parts.append("")
            parts.append(kv)
        if record.exc_info and record.exc_info[1]:
            parts.append("\n" + self.formatException(record.exc_info))
        return " ".join(parts)

    def _format_json(self, record: logging.LogRecord, extra: dict[str, Any], ts: str) -> str:
        data: dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.message,
        }
        data.update(extra)
        if record.exc_info and record.exc_info[1]:
            data["exc"] = "".join(traceback.format_exception(*record.exc_info))
        return json.dumps(data, default=str)


def configure_logging(
    *,
    log_format: str = "",
    log_level: str = "INFO",
) -> None:
    """Configure root logger with structured formatter.

    Call once at startup before any log statements.

    Args:
        log_format: Set to "json" for JSON output. Default is human-readable console.
        log_level: Log level (DEBUG, INFO, WARNING, ERROR). Default is INFO.

    Build context (version + commit) is attached to every record passing
    through the StreamHandler installed here, via
    a ``_BuildContextFilter``. This is intentional handler-scoped behaviour:
    handlers added externally to the root logger (e.g. a user-installed
    ``FileHandler`` for local file logging) will **not** receive the filter
    and their output will not carry version/commit. Re-attach the filter
    explicitly if you wire up a custom handler outside this function.
    """
    json_mode = log_format.lower() == "json"
    level_name = log_level.upper()
    level = getattr(logging, level_name, logging.INFO)

    formatter = StructuredFormatter(json_mode=json_mode)
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    # Build-context filter: attaches version+commit to every log record so
    # remote bug reports identify the build from a single line.
    build_filter = _BuildContextFilter(*build_info())
    handler.addFilter(build_filter)

    root = logging.getLogger()
    # Only replace exact StreamHandlers; preserve subclasses (e.g., FileHandler)
    root.handlers = [
        h
        for h in root.handlers
        if type(h) is not logging.StreamHandler  # pylint: disable=unidiomatic-typecheck
    ]
    root.addHandler(handler)
    root.setLevel(level)
