"""
SE24 (Class Builder) lookup tool.

This module provides a tool to look up class/interface metadata from SE24,
returning strongly-typed Pydantic models with method and attribute details.
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
from sapwebguimcp.backend.webgui.parsers.se24_parser import (
    SE24TabSnapshots,
    count_se24_grid_rows,
    parse_se24_snapshot,
)
from sapwebguimcp.backend.webgui.types import AriaSnapshot
from sapwebguimcp.models import (
    SE24Entry,
    SE24Error,
    SE24FileSummary,
    SE24Result,
    TableData,
)
from sapwebguimcp.tools.field_helpers import fill_and_display

if TYPE_CHECKING:
    from sapwebguimcp.backend.webgui.backend import WebGuiBackend
    from sapwebguimcp.lang.schema import LanguagePack
    from sapwebguimcp.lang.text import Text


logger = logging.getLogger(__name__)

__all__ = ["register_se24_tools"]

# Threshold for writing to file instead of returning inline
MAX_INLINE_OBJECTS = 5


# =============================================================================
# SE24 Navigation Helpers
# =============================================================================


async def _capture_tab_snapshot(backend: WebGuiBackend, tab: Text) -> str | None:
    """Click a tab and capture its snapshot. Returns snapshot or None.

    After clicking, verifies the tab is actually ``[selected]`` in the ARIA
    snapshot.  SAP WebGUI sometimes needs an extra ``wait_for_ready`` before
    the tab content is rendered.
    """
    for name in tab:
        try:
            await backend.click_tab(name)
            await backend.wait_for_ready()
            snapshot = str(await backend.get_snapshot())
            # Verify the tab actually switched by checking [selected] marker
            if f'tab "{name}" [selected]' in snapshot:
                return snapshot
            logger.warning("Tab '%s' clicked but not selected in snapshot, retrying", name)
            # Retry once — SAP may need a moment
            await backend.click_tab(name)
            await backend.wait_for_ready()
            snapshot = str(await backend.get_snapshot())
            if f'tab "{name}" [selected]' in snapshot:
                return snapshot
            logger.warning("Tab '%s' still not selected after retry", name)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.debug("Tab '%s' click failed, trying next variant", name, exc_info=True)
            continue

    logger.warning("Could not activate tab '%s' with any label variant", " / ".join(tab))
    return None


async def _fill_and_display(backend: WebGuiBackend, class_name: str, t: LanguagePack) -> SE24Error | None:
    """Fill the class field and press F7 (Display). Returns error or None.

    Delegates to the shared ``fill_and_display`` helper which uses real
    keyboard events and polls for page navigation.
    """
    error_msg = await fill_and_display(
        backend,
        list(t.se24.class_field_label),
        class_name,
        t,
        tcode_label="class/interface",  # lang-ok: our own message
    )
    if error_msg:
        return SE24Error(
            class_name=class_name,
            error=error_msg,
            retrieved_at=datetime.now(UTC),
        )
    return None


async def _read_interfaces_table(
    backend: WebGuiBackend, class_name: str, interfaces_snapshot: AriaSnapshot
) -> TableData | None:
    """Read the interfaces grid of the open interfaces tab. Returns None when the read fails.

    The ARIA snapshot of the grid names only the cells in view and carries no values of the text boxes, so the
    interface names come from a table read. A window as full as the table read warns that rows may be cut off.
    """
    try:
        table = await backend.read_table()
    except Exception:  # pylint: disable=broad-exception-caught
        logger.warning("Could not read the interfaces table", extra={"object": class_name}, exc_info=True)
        return None
    visible_rows = count_se24_grid_rows(interfaces_snapshot)
    if 0 < visible_rows <= len(table.rows):
        logger.warning(
            "The interface table fills the visible rows, interface list may be cut off at the visible rows",
            extra={"object": class_name, "rows_read": len(table.rows), "visible_rows": visible_rows},
        )
    return table


async def _lookup_class_on_initial_screen(
    backend: WebGuiBackend, class_name: str, t: LanguagePack
) -> SE24Entry | SE24Error:
    """Look up a class assuming we're already on the SE24 initial screen.

    After a successful lookup, the browser will be on the class detail screen.
    The caller handles navigation between lookups (via ``enter_transaction``).
    """
    # Ensure the SE24 screen is fully loaded before interacting.
    await backend.wait_for_ready()

    # Fill class name, press F7, and verify we left the initial screen.
    error = await _fill_and_display(backend, class_name, t)
    if error:
        return error

    # Get main snapshot first
    main_snapshot = AriaSnapshot(await backend.get_snapshot())
    logger.debug("Got main snapshot", extra={"object": class_name, "length": len(str(main_snapshot))})

    # Capture each tab. The properties tab carries description, package, superclass and the abstract/final flags.
    properties_raw = await _capture_tab_snapshot(backend, t.se24.properties_tab)
    if properties_raw is None:
        logger.warning(
            "Properties tab not available, description, package, superclass and flags stay empty",
            extra={"object": class_name},
        )
    methods_raw = await _capture_tab_snapshot(backend, t.se24.methods_tab)
    attributes_raw = await _capture_tab_snapshot(backend, t.se24.attributes_tab)
    interfaces_raw = await _capture_tab_snapshot(backend, t.se24.interfaces_tab)
    interfaces_snapshot = AriaSnapshot(interfaces_raw) if interfaces_raw is not None else None
    interfaces_table = (
        await _read_interfaces_table(backend, class_name, interfaces_snapshot) if interfaces_snapshot else None
    )
    tab_snapshots = SE24TabSnapshots(
        methods_tab=AriaSnapshot(methods_raw) if methods_raw is not None else None,
        attributes_tab=AriaSnapshot(attributes_raw) if attributes_raw is not None else None,
        interfaces_tab=interfaces_snapshot,
        properties_tab=AriaSnapshot(properties_raw) if properties_raw is not None else None,
        interfaces_table=interfaces_table,
    )

    # Parse all snapshots
    return parse_se24_snapshot(
        snapshot=main_snapshot,
        class_name=class_name,
        t=t,
        tab_snapshots=tab_snapshots,
    )


async def _lookup_batch_se24_webgui(backend: WebGuiBackend, class_list: list[str], t: LanguagePack) -> SE24Result:
    """Run SE24 lookups for a batch of classes on the WebGUI backend."""
    entries: list[SE24Entry] = []
    errors: list[SE24Error] = []

    for class_name in class_list:
        await backend.enter_transaction("/n")
        await backend.wait_for_ready()
        tx_result = await backend.enter_transaction("SE24")
        if not tx_result.success:
            errors.append(
                SE24Error(
                    class_name=class_name,
                    error=f"Failed to navigate to SE24: {tx_result.error}",
                    retrieved_at=datetime.now(UTC),
                )
            )
            continue
        await backend.wait_for_ready()
        try:
            result = await _lookup_class_on_initial_screen(backend, class_name, t)
            if isinstance(result, SE24Entry):
                entries.append(result)
            else:
                errors.append(result)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.exception("Looking up in SE24", extra={"object": class_name})
            errors.append(
                SE24Error(
                    class_name=class_name, error=f"Error looking up '{class_name}': {e}", retrieved_at=datetime.now(UTC)
                )
            )

    if entries:
        return SE24Result(entries=entries, errors=errors)
    return SE24Result.failure(error=f"All {len(errors)} lookups failed", entries=[], errors=errors)


# =============================================================================
# MCP Tool Registration
# =============================================================================


def register_se24_tools(mcp: FastMCP) -> None:
    """Register SE24 tools with the MCP server."""

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            open_world_hint=False,
        ),
        description=(
            "Look up class/interface metadata from SE24 (Class Builder). "
            "If sap-adt is available, prefer its get_source/get_class_definition tools. "
            "USE THIS instead of sap_transaction('SE24') - faster and returns structured data. "
            "Returns class structure including methods with parameters, "
            "attributes, and implemented interfaces. Supports single class or list of classes. "
            "Each method includes: name, visibility, parameters, exceptions, and description."
        ),
    )
    async def sap_se24_lookup(
        classes: str | list[str],
        output_file: str | None = None,
        session: str | None = None,
        agent_id: str | None = None,
    ) -> SE24Result | SE24FileSummary:
        """
        Look up class/interface metadata from SE24.

        Args:
            classes: Single class/interface name or list of names
                (e.g., 'CL_SALV_TABLE' or ['CL_SALV_TABLE', 'CL_ABAP_CHAR_UTILITIES'])
            output_file: If provided, write full results to this JSON file and return summary.
                        Recommended for >5 classes to avoid context overflow.
            session: Session ID (e.g., "s1", "s2"). None uses primary session.
            agent_id: Agent identifier for binding check. Optional.

        Returns:
            SE24Result with entries and errors (inline), or
            SE24FileSummary with file path and statistics (when output_file provided)
        """
        class_list = [classes] if isinstance(classes, str) else list(classes)

        if not class_list:
            return SE24Result.failure("No classes provided")

        try:
            backend = await get_backend(session=session, agent_id=agent_id, tool_name="sap_se24_lookup")
        except ValueError as e:
            return SE24Result.failure(f"Session error: {e}")

        # Resolved once, outside the per-class error handling: an unsupported language must not become an entry error
        t = lang.current("sap_se24_lookup")

        final_result = await _lookup_batch_se24_webgui(backend, class_list, t)

        # Write to file if requested
        if output_file:
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with output_path.open("w", encoding="utf-8") as f:
                json.dump(final_result.model_dump(mode="json"), f, indent=2, ensure_ascii=False)

            return SE24FileSummary(
                success=final_result.success,
                error=final_result.error,
                output_file=str(output_path.absolute()),
                total_requested=len(class_list),
                successful=len(final_result.entries),
                failed=len(final_result.errors),
                sample_entries=[e.class_name for e in final_result.entries[:5]],
                sample_errors=[e.class_name for e in final_result.errors[:5]],
            )

        if len(class_list) > MAX_INLINE_OBJECTS:
            logger.warning(
                "Returning classes inline - consider using output_file parameter",
                extra={"count": len(class_list)},
            )

        return final_result
