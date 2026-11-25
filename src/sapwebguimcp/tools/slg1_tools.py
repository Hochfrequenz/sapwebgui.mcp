"""
SLG1 (Application Log) lookup tool.

This module provides a tool to search and read SAP application logs via SLG1,
returning strongly-typed Pydantic models with log entries.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from sapwebguimcp import lang
from sapwebguimcp.backend.manager import get_backend
from sapwebguimcp.backend.webgui.parsers.slg1_parser import (
    is_slg1_initial_screen,
    is_slg1_no_results,
    parse_slg1_log_list,
)
from sapwebguimcp.backend.webgui.types import AriaSnapshot
from sapwebguimcp.models.slg1_models import (
    SLG1FileSummary,
    SLG1LogListResult,
)
from sapwebguimcp.user_date_format import resolve_user_date_format
from sapwebguimcp.utils import format_sap_date_as

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sapwebguimcp.backend.webgui.backend import WebGuiBackend
    from sapwebguimcp.lang import LanguagePack
    from sapwebguimcp.lang.text import Text


logger = logging.getLogger(__name__)

__all__ = ["register_slg1_tools"]


async def _fill_by_label(backend: "WebGuiBackend", labels: Iterable[str], value: str) -> bool:
    """Fill the field with the first of ``labels`` the screen shows. False if none is found or the value is refused."""
    for label in labels:
        result = await backend.fill_form({label: value})
        if label in result.not_found:
            continue
        return not result.errors  # found: if it errored, the value was not accepted
    return False


async def _slg1_lookup(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-branches,too-many-locals
    backend: "WebGuiBackend",
    t: LanguagePack,
    object_name: str,
    subobject: str | None = None,
    external_id: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> SLG1LogListResult:
    """Execute SLG1 lookup and return parsed results."""
    now = datetime.now(UTC)

    # Navigate to SLG1
    tx_result = await backend.enter_transaction("SLG1")
    if not tx_result.success:
        return SLG1LogListResult.failure(
            f"Failed to navigate to SLG1: {tx_result.error}",
            logs=[],
            log_count=0,
            logs_truncated=False,
            retrieved_at=now,
        )

    # Wait for SLG1 selection screen to fully load
    await backend.wait_for_ready()

    # Fill the selection screen, one field at a time: each field is looked up by the labels of the session's view
    fields: list[tuple[Text, str]] = [(t.slg1.log_object, object_name)]
    if subobject:
        fields.append((t.slg1.log_subobject, subobject))
    if external_id:
        fields.append((t.slg1.external_id, external_id))
    if from_date or to_date:
        # The date field is pre-filled: read the user's date format off it before it is overwritten (#42)
        date_format = await resolve_user_date_format(
            backend, [*t.slg1.from_datetime, *t.slg1.to_datetime], t.date_format
        )
        if from_date:
            fields.append((t.slg1.from_datetime, format_sap_date_as(from_date, date_format)))
        if to_date:
            fields.append((t.slg1.to_datetime, format_sap_date_as(to_date, date_format)))
    for labels, value in fields:
        if not await _fill_by_label(backend, labels, value):
            logger.warning("SLG1 field not found labels=%r", list(labels))

    # Execute search (F8)
    await backend.press_key("F8")
    await backend.wait_for_ready()

    # Capture result snapshot
    snapshot = AriaSnapshot(await backend.get_snapshot())

    # Check for no results (explicit status bar message)
    if is_slg1_no_results(snapshot, t):
        return SLG1LogListResult(
            logs=[],
            log_count=0,
            logs_truncated=False,
            filters_applied=_build_filters(object_name, subobject, external_id, from_date, to_date),
            retrieved_at=now,
        )

    # If still on initial screen after F8, read status bar for error details
    if is_slg1_initial_screen(snapshot, t):
        sb_info = await backend.get_status_bar()
        if sb_info.type in ("error", "warning", "E", "W"):
            return SLG1LogListResult.failure(
                f"SLG1 error: {sb_info.message}",
                logs=[],
                log_count=0,
                logs_truncated=False,
                retrieved_at=now,
            )
        # No error in status bar — genuinely no results
        return SLG1LogListResult(
            logs=[],
            log_count=0,
            logs_truncated=False,
            filters_applied=_build_filters(object_name, subobject, external_id, from_date, to_date),
            retrieved_at=now,
        )

    # Parse the log list
    result = parse_slg1_log_list(snapshot, t)
    result.filters_applied = _build_filters(object_name, subobject, external_id, from_date, to_date)
    return result


def _build_filters(
    object_name: str,
    subobject: str | None,
    external_id: str | None,
    from_date: str | None,
    to_date: str | None,
) -> dict[str, str]:
    """Build filters_applied dict from parameters."""
    filters: dict[str, str] = {"object": object_name}
    if subobject:
        filters["subobject"] = subobject
    if external_id:
        filters["external_id"] = external_id
    if from_date:
        filters["from_date"] = from_date
    if to_date:
        filters["to_date"] = to_date
    return filters


# =============================================================================
# MCP Tool Registration
# =============================================================================


def register_slg1_tools(mcp: FastMCP) -> None:
    """Register SLG1 tools with the MCP server."""

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            open_world_hint=False,
        ),
        description=(
            "Search and read SAP application logs from SLG1. "
            "USE THIS instead of sap_transaction('SLG1') - faster and returns structured data. "
            "Returns log entries with metadata (date, time, user, object, subobject, external ID, "
            "message count, log number). Best used when the log object is known "
            "(e.g., /SDF/CALM for Cloud ALM, /SDF/AIMAX for AI). "
            "Use '*' as object to search all logs. "
            "Requires at minimum the 'object' parameter. "
            "Returns up to 50 logs."
        ),
    )
    async def sap_slg1_lookup(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        object: str,  # noqa: A002  # pylint: disable=redefined-builtin
        subobject: str | None = None,
        external_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        output_file: str | None = None,
        session: str | None = None,
        agent_id: str | None = None,
    ) -> SLG1LogListResult | SLG1FileSummary:
        """
        Search and read SAP application logs from SLG1.

        Args:
            object: Log object (e.g., '/SDF/CALM', '/SDF/AIMAX', '*' for all)
            subobject: Log subobject (optional filter)
            external_id: External identifier (optional filter)
            from_date: Start date filter (YYYY-MM-DD format)
            to_date: End date filter (YYYY-MM-DD format)
            output_file: If provided, write results to this JSON file and return summary.
            session: Session ID (e.g., "s1", "s2"). None uses primary session.
            agent_id: Agent identifier for binding check. Optional.

        Returns:
            SLG1LogListResult with log entries, or
            SLG1FileSummary with file path when output_file is provided.
        """
        try:
            backend = await get_backend(session=session, agent_id=agent_id, tool_name="sap_slg1_lookup")
        except ValueError as e:
            return SLG1LogListResult.failure(
                f"Session error: {e}",
                logs=[],
                log_count=0,
                logs_truncated=False,
                retrieved_at=datetime.now(UTC),
            )

        # Outside the try below: a session language without a pack (UnsupportedLanguageError) fails the call.
        t = lang.current("sap_slg1_lookup")

        try:
            result = await _slg1_lookup(
                backend,
                t,
                object,
                subobject,
                external_id,
                from_date,
                to_date,
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.exception("SLG1 lookup failed")
            result = SLG1LogListResult.failure(
                f"SLG1 lookup error: {e}",
                logs=[],
                log_count=0,
                logs_truncated=False,
                retrieved_at=datetime.now(UTC),
            )

        # Write to file if requested (only on success)
        if output_file and result.success:
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with output_path.open("w", encoding="utf-8") as f:
                json.dump(result.model_dump(mode="json"), f, indent=2, ensure_ascii=False)

            total_messages = sum(log.message_count for log in result.logs)
            return SLG1FileSummary(
                success=result.success,
                error=result.error,
                output_file=str(output_path.absolute()),
                log_count=result.log_count,
                total_messages=total_messages,
                logs_truncated=result.logs_truncated,
                retrieved_at=result.retrieved_at,
            )

        return result
