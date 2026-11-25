"""
SM37 (Job Overview) lookup tool.

Provides a read-only tool to list background jobs from SM37
with status/date/user filters, and optionally retrieve job logs.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from sapwebguimcp import lang
from sapwebguimcp.backend.manager import get_backend
from sapwebguimcp.backend.webgui.parsers.sm37_parser import (
    is_no_jobs_found,
    parse_sm37_job_list,
    parse_sm37_job_log,
)
from sapwebguimcp.backend.webgui.types import AriaSnapshot
from sapwebguimcp.lang.schema import JobStatus
from sapwebguimcp.models.screen_state import SelectionScreenState
from sapwebguimcp.models.sm37_models import SM37JobListResult, SM37JobLog
from sapwebguimcp.tools.screen_state_helpers import ensure_screen_state
from sapwebguimcp.utils import format_sap_date_as

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sapwebguimcp.backend.webgui.backend import WebGuiBackend
    from sapwebguimcp.lang import LanguagePack


logger = logging.getLogger(__name__)

__all__ = ["register_sm37_tools"]

_MAX_JOBS = 200

_STATUS_PARAMS: dict[str, JobStatus] = {
    "scheduled": JobStatus.SCHEDULED,  # lang-ok: tool parameter value
    "released": JobStatus.RELEASED,  # lang-ok: tool parameter value
    "ready": JobStatus.READY,  # lang-ok: tool parameter value
    "active": JobStatus.ACTIVE,  # lang-ok: tool parameter value
    "finished": JobStatus.FINISHED,  # lang-ok: tool parameter value
    "canceled": JobStatus.CANCELED,  # lang-ok: tool parameter value
}
"""The ``status`` values of the tool and the job status each one selects."""


def _is_applied(labels: Iterable[str], not_applied: set[str]) -> bool:
    """A control is applied if at least one of its labels (the one of the screen's language) was not reported."""
    return any(label not in not_applied for label in labels)


async def _fill_selection_screen(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-branches,too-many-locals
    backend: "WebGuiBackend",
    t: LanguagePack,
    job_name: str,
    username: str | None,
    statuses: list[str] | None,
    from_date: str | None,
    to_date: str | None,
) -> list[str]:
    """Fill the SM37 selection screen fields.

    Returns:
        The names of the requested filters that could not be applied, a subset of
        ``job_name, username, status, from_date, to_date`` in that order; empty if every requested filter was applied.
        A filter counts as applied if at least one label of its control (the one of the screen's language) was found
        and set. ``username`` is only reported when a user was requested and ``status`` only when statuses were
        requested, then if any of the six status checkboxes (to check or to uncheck) could not be set. If the screen
        state could not be established at all, every filter handed to it is reported.
    """
    unapplied: list[str] = []

    # Build target for checkboxes + text fields in one declarative call. Every label of the session's view is a key:
    # ensure_screen_state matches by label; a label that is not on the screen (the other language) is reported in
    # ``not_applied``, which is only a failure when no label of a requested filter was applied.
    effective_statuses = set(statuses) if statuses else set(_STATUS_PARAMS)
    fields: dict[str, str] = dict.fromkeys(t.sm37.job_name, job_name)
    if username is not None:
        fields.update(dict.fromkeys(t.sm37.user_name, username))

    target = SelectionScreenState(
        checkboxes={
            label: param in effective_statuses
            for param, status in _STATUS_PARAMS.items()
            for label in t.sm37.status[status]
        },
        fields=fields,
    )
    state_result = await ensure_screen_state(backend, target)
    errors: list[str] = []
    if not state_result.success:
        errors.append(f"Failed to set selection screen state: {state_result.error}")  # lang-ok: our own message
        unapplied.append("job_name")
        if username is not None:
            unapplied.append("username")
        if statuses:
            unapplied.append("status")
    else:
        not_applied = set(state_result.not_applied)
        if not _is_applied(t.sm37.job_name, not_applied):
            unapplied.append("job_name")
        if username is not None and not _is_applied(t.sm37.user_name, not_applied):
            unapplied.append("username")
        # Without a requested status no filter was asked for; the boxes are only set to keep SAP's defaults visible.
        if statuses and not all(_is_applied(t.sm37.status[status], not_applied) for status in _STATUS_PARAMS.values()):
            unapplied.append("status")
        errors.extend(state_result.warnings)
    if errors:
        logger.warning("Selection screen state errors=%r", errors)

    # Date fields are filled manually (not via ensure_screen_state) because they
    # require the date format of the session's language.
    # The ARIA snapshot values use SAP's display format which may differ from the
    # input format, making snapshot-based verification unreliable for dates.
    for name, value, labels in (("from_date", from_date, t.sm37.from_date), ("to_date", to_date, t.sm37.to_date)):
        if not value:
            continue
        sap_value = format_sap_date_as(value, t.date_format)
        for label in labels:
            try:
                await backend.fill_field(label, sap_value)
                break
            except ValueError:
                continue
        else:
            unapplied.append(name)

    return unapplied


def _is_job_log_screen(snapshot: str, t: LanguagePack) -> bool:
    """Check if the snapshot shows a job log screen (not the job list).

    The heading is the one of S/4HANA; SAP ERP 6.0 titles the screen "Job-Log zu Job <name> / <id>" instead.
    """
    return t.sm37.job_log_heading.contains(snapshot) or t.sm37.job_log_title_ecc.contains(snapshot)


async def _click_job_log_button(backend: "WebGuiBackend", t: LanguagePack) -> bool:
    """Click the Job-Log button, trying each of its labels. False if the screen has none of them."""
    for label in t.sm37.job_log_button:
        try:
            await backend.click_button(label)
            return True
        except ValueError:
            continue
    logger.warning("Job log button not found labels=%r", list(t.sm37.job_log_button))
    return False


async def _fetch_job_log(backend: "WebGuiBackend", t: LanguagePack) -> SM37JobLog | None:
    """
    Select the first job row and fetch its job log.

    Clicks the Job-Log button, validates the screen changed, then parses the log.
    """
    try:
        # Select the first job row before clicking Job-Log
        await backend.click_table_cell(1, 0, "click")
        await backend.wait_for_ready()

        # Click the Job-Log button
        if not await _click_job_log_button(backend, t):
            return None

        await backend.wait_for_ready()

        snapshot = AriaSnapshot(await backend.get_snapshot())

        if not _is_job_log_screen(str(snapshot), t):
            logger.warning("Expected job log screen but got something else, skipping log parse")
            await backend.press_key("F3")
            await backend.wait_for_ready()
            return None

        job_log = parse_sm37_job_log(snapshot, "", t)

        # Navigate back (F3)
        await backend.press_key("F3")
        await backend.wait_for_ready()

        return job_log

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.exception("Fetching job log error=%s", e)
        return None


async def _execute_sm37_lookup(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals,too-many-branches
    backend: "WebGuiBackend",
    t: LanguagePack,
    job_name: str,
    username: str | None,
    statuses: list[str] | None,
    from_date: str | None,
    to_date: str | None,
    include_log: bool,
) -> SM37JobListResult:
    """Execute the SM37 lookup workflow on the given backend."""
    now = datetime.now(UTC)

    tx_result = await backend.enter_transaction("SM37")
    if not tx_result.success:
        return SM37JobListResult.failure(
            error=f"Failed to navigate to SM37: {tx_result.error}",
            jobs=[],
            job_count=0,
            filters_applied={},
            retrieved_at=now,
        )

    await backend.wait_for_ready()

    unapplied = await _fill_selection_screen(backend, t, job_name, username, statuses, from_date, to_date)
    if unapplied:
        # Pressing F8 now would run SAP's default selection and return jobs that do not match the request.
        logger.warning("SM37 filters not applied filters=%r", unapplied)
        names = ", ".join(unapplied)
        return SM37JobListResult.failure(
            error=f"Could not apply the filter(s) on the SM37 selection screen: {names}",  # lang-ok: our own message
            jobs=[],
            job_count=0,
            filters_applied={},
            retrieved_at=now,
        )

    filters_applied: dict[str, str] = {"job_name": job_name}
    if username:
        filters_applied["username"] = username
    if statuses:
        filters_applied["status"] = ",".join(statuses)
    if from_date:
        filters_applied["from_date"] = from_date
    if to_date:
        filters_applied["to_date"] = to_date

    # Execute (F8)
    await backend.press_key("F8")
    await backend.wait_for_ready()

    snapshot = AriaSnapshot(await backend.get_snapshot())

    if is_no_jobs_found(snapshot, t):
        return SM37JobListResult(
            jobs=[],
            job_count=0,
            filters_applied=filters_applied,
            retrieved_at=now,
        )

    jobs = parse_sm37_job_list(snapshot, t)

    jobs_truncated = len(jobs) > _MAX_JOBS
    if jobs_truncated:
        logger.warning("Truncating job list total=%d max=%d", len(jobs), _MAX_JOBS)
        jobs = jobs[:_MAX_JOBS]

    # Fetch job log if requested and exactly one job
    job_log: SM37JobLog | None = None
    if include_log and len(jobs) == 1:
        job_log = await _fetch_job_log(backend, t)
        if job_log:
            job_log.job_name = jobs[0].job_name

    return SM37JobListResult(
        jobs=jobs,
        job_count=len(jobs),
        jobs_truncated=jobs_truncated,
        filters_applied=filters_applied,
        job_log=job_log,
        retrieved_at=now,
    )


def register_sm37_tools(mcp: FastMCP) -> None:
    """Register SM37 tools with the MCP server."""

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            open_world_hint=False,
        ),
        description=(
            "List background jobs from SM37 (Job Overview). "
            "USE THIS instead of sap_transaction('SM37') - faster and returns structured data.\n\n"
            "Filters: job name (wildcards like *BILLING*), username, status "
            "(scheduled/released/ready/active/finished/canceled), date range.\n\n"
            "Note: status=None keeps SAP defaults (all checked except 'Scheduled'). "
            "Pass status=['scheduled'] explicitly to include only scheduled jobs.\n\n"
            "When include_log=True and exactly one job matches, the job log is included.\n\n"
            "Returns job list with name, status, start time, duration, user, and SAP client (mandant)."
        ),
    )
    async def sap_sm37_lookup(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        job_name: str = "*",
        username: str | None = "*",
        status: (
            list[
                Literal[
                    "scheduled",  # lang-ok: tool parameter values
                    "released",  # lang-ok: tool parameter values
                    "ready",  # lang-ok: tool parameter values
                    "active",  # lang-ok: tool parameter values
                    "finished",  # lang-ok: tool parameter values
                    "canceled",  # lang-ok: tool parameter values
                ]
            ]
            | None
        ) = None,
        from_date: str | None = None,
        to_date: str | None = None,
        include_log: bool = False,
        output_file: str | None = None,
        session: str | None = None,
        agent_id: str | None = None,
    ) -> SM37JobListResult:
        """
        List background jobs from SM37.

        Args:
            job_name: Job name filter (supports * wildcard, default: *)
            username: User filter (default: * for all users, None to keep SAP default)
            status: Status filter list (default: None = all statuses).
            from_date: Start date filter in ISO format (YYYY-MM-DD)
            to_date: End date filter in ISO format (YYYY-MM-DD)
            include_log: Fetch job log when exactly one job matches (default: False)
            output_file: If provided, write full results to this JSON file
            session: Session ID (e.g., "s1", "s2"). None uses primary session.
            agent_id: Agent identifier for binding check. Optional.
        """
        try:
            backend = await get_backend(session=session, agent_id=agent_id, tool_name="sap_sm37_lookup")
        except ValueError as e:
            return SM37JobListResult.failure(
                error=f"Session error: {e}",
                jobs=[],
                job_count=0,
                filters_applied={},
                retrieved_at=datetime.now(UTC),
            )

        # Outside any try: a session language without a pack (UnsupportedLanguageError) fails the call.
        t = lang.current("sap_sm37_lookup")

        result = await _execute_sm37_lookup(
            backend=backend,
            t=t,
            job_name=job_name,
            username=username,
            statuses=list(status) if status else None,
            from_date=from_date,
            to_date=to_date,
            include_log=include_log,
        )

        if output_file and result.success:
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as f:
                json.dump(result.model_dump(mode="json"), f, indent=2, ensure_ascii=False)
            logger.info("Wrote SM37 results path=%s", str(output_path))

        return result
