"""
SE24 (Class Builder) edit tool.

Provides sap_se24_edit for modifying existing class methods with
syntax check, activation, and auto-revert on failure.

Unlike SE38/SE37 which edit entire program/FM source, SE24 edits
individual method source code within a class.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from sapwebguimcp import lang
from sapwebguimcp.backend.manager import get_backend
from sapwebguimcp.models.se24_edit_models import SE24EditResult
from sapwebguimcp.tools.edit_helpers import describe_failed_replace
from sapwebguimcp.tools.field_helpers import fill_field_with_keyboard, toggle_to_change_mode

if TYPE_CHECKING:
    from sapwebguimcp.backend.webgui.backend import WebGuiBackend
    from sapwebguimcp.lang.schema import LanguagePack


logger = logging.getLogger(__name__)


async def _fill_class_field(backend: WebGuiBackend, class_name: str, attempt: int, t: LanguagePack) -> bool:
    """Fill the SE24 class name field. attempt==0 uses JS, retries use keyboard."""
    if attempt == 0:
        for label in t.se24.object_type:
            try:
                await backend.fill_field(label, class_name)
                return True
            except ValueError:
                continue
        return await backend.fill_main_input(class_name, list(t.se24.object_type))
    return await fill_field_with_keyboard(backend, list(t.se24.object_type), class_name)


async def _open_class_in_change_mode(backend: WebGuiBackend, class_name: str, t: LanguagePack) -> str | None:
    """Navigate to SE24, display class via F7, and toggle to change mode.

    Returns error message or None on success.
    """
    # bring_to_front is required for SE24: without it, F7/field interactions fail silently
    await backend.bring_to_front()

    await backend.enter_transaction("SE24")

    # Fill class name and press F7. First attempt uses JS fill (fast),
    # retries use real keyboard events (survives SAP state resets after /n).
    for attempt in range(3):
        if attempt > 0:
            logger.info("Retrying fill+F7 for %s (attempt %d)", class_name, attempt + 1)
            await asyncio.sleep(1.0)

        filled = await _fill_class_field(backend, class_name, attempt, t)
        if not filled:
            logger.warning("Class name field not found (attempt %d)", attempt + 1)
            continue

        # Brief wait for SAP to register the typed value before pressing F7.
        await asyncio.sleep(0.3)
        await backend.press_key("F7")
        await backend.wait_for_ready()

        # Check if we left the initial screen.
        snapshot = str(await backend.get_snapshot())
        if t.se24.class_builder.contains(snapshot):
            break
    else:
        return "Could not find or fill class name field after retries"

    await backend.dismiss_language_dialog()

    return await toggle_to_change_mode(backend, t)


async def _select_method_and_open_source(
    backend: WebGuiBackend, class_name: str, method_name: str, t: LanguagePack
) -> str | None:
    """Select method in methods grid and open its source editor.

    Returns error message or None on success.
    """
    # Ensure we're on the Methods tab
    for tab_label in t.se24.methods_tab:
        try:
            await backend.click_tab(tab_label)
            break
        except ValueError:
            continue
    else:
        return "Could not find the methods tab"  # lang-ok: our own message
    await backend.wait_for_ready()

    # Select the method in the grid by finding it in the table
    table = await backend.read_table()
    row_index = None
    for i, row in enumerate(table.rows):
        if any(method_name.upper() in v.upper() for v in row.data.values() if v):
            row_index = i
            break
    if row_index is None:
        snapshot = await backend.get_snapshot()
        logger.warning(
            "SE24 edit: method %s not found for %s. Screen: %s",
            method_name,
            class_name,
            str(snapshot)[:200],
        )
        return f"Method '{method_name}' not found in class '{class_name}' methods grid"  # lang-ok: our own message
    await backend.click_table_cell(row_index + 1, 0, "click")  # 1-based row index
    await backend.wait_for_ready()

    # Click the source code button to open the method source
    for btn_name in t.se24.source_button:
        try:
            await backend.click_button(btn_name)
            await backend.wait_for_ready()
            break
        except Exception:  # pylint: disable=broad-exception-caught
            continue
    else:
        return "Could not find the source code button"  # lang-ok: our own message

    return None


async def _navigate_to_method_editor(
    backend: WebGuiBackend, class_name: str, method_name: str, t: LanguagePack
) -> str | None:
    """Navigate to SE24, open class in change mode, select method, open source editor.

    Returns error message or None on success.
    """
    error = await _open_class_in_change_mode(backend, class_name, t)
    if error:
        return error
    return await _select_method_and_open_source(backend, class_name, method_name, t)


async def _edit_check_activate_method(
    backend: WebGuiBackend, class_name: str, method_name: str, new_source: str, t: LanguagePack
) -> SE24EditResult:
    """Core edit logic: navigate, read backup, replace, check, activate, revert on failure."""
    nav_error = await _navigate_to_method_editor(backend, class_name, method_name, t)
    if nav_error:
        return SE24EditResult.failure(
            error=nav_error, class_name=class_name, method_name=method_name, backup_source="", activated=False
        )

    # Read current source (backup)
    backup_source = await backend.read_editor_source() or ""
    if not backup_source:
        return SE24EditResult.failure(
            error="Could not read current method source code from editor. Is the class/method accessible?",
            class_name=class_name,
            method_name=method_name,
            backup_source="",
            activated=False,
        )

    logger.info("SE24 edit: backup saved for %s->%s (%d chars)", class_name, method_name, len(backup_source))

    # Replace editor content
    replaced = await backend.replace_editor_source(new_source)
    if not replaced:
        return SE24EditResult.failure(
            error=await describe_failed_replace(backend, backup_source),
            class_name=class_name,
            method_name=method_name,
            backup_source=backup_source,
            activated=False,
        )

    # Check and activate
    result = await backend.check_and_activate()

    if not result.success:
        logger.warning("SE24 edit: check/activate failed for %s->%s, reverting", class_name, method_name)
        reverted = await backend.replace_editor_source(backup_source)
        if reverted:
            revert_result = await backend.check_and_activate()
            if revert_result.success:
                result.messages.append("Auto-reverted to original source and re-activated successfully")
            else:
                result.messages.append(
                    f"Auto-reverted source but re-activation failed: {'; '.join(revert_result.messages)}"
                )
        else:
            result.messages.append("WARNING: Auto-revert failed! Manual intervention needed.")

        return SE24EditResult.failure(
            error=f"Check/activate failed: {'; '.join(result.messages)}",
            class_name=class_name,
            method_name=method_name,
            backup_source=backup_source,
            check_messages=result.messages,
            activated=False,
        )

    return SE24EditResult(
        success=True,
        class_name=class_name,
        method_name=method_name,
        backup_source=backup_source,
        check_messages=result.messages,
        activated=result.activated,
    )


def register_se24_edit_tools(mcp: FastMCP) -> None:
    """Register SE24 edit tools with the MCP server."""

    @mcp.tool(
        description=(
            "Edit an existing class method in SE24 (Class Builder). "
            "If sap-adt is available, prefer its patch_source or "
            "set_source_from_file tools — faster, no GUI needed.\n\n"
            "Replaces the method's source code, runs syntax check (Ctrl+F2), "
            "and activates (Ctrl+F3). Auto-reverts if check or activation fails.\n\n"
            "**Important:** Only for EXISTING classes and methods. To create new ones, use abapGit.\n\n"
            "**Workflow:** Read current class with sap_se24_lookup first to see methods, "
            "then call this tool with the full new method source."
        ),
        annotations=ToolAnnotations(
            destructive_hint=True,
            read_only_hint=False,
            idempotent_hint=False,
        ),
    )
    async def sap_se24_edit(
        class_name: str,
        method_name: str,
        new_source: str,
        session: str | None = None,
        agent_id: str | None = None,
    ) -> SE24EditResult:
        """Edit an existing class method, check syntax, and activate.

        Args:
            class_name: Name of the class (e.g., 'ZCL_TEST_MCP_EDIT').
            method_name: Name of the method to edit (e.g., 'DO_SOMETHING').
            new_source: Complete new ABAP method source code to replace the current code.
            session: Session ID (e.g., "s1", "s2"). None uses primary session.
            agent_id: Agent identifier for binding check. Optional.

        Returns:
            SE24EditResult with success status, backup source, and check messages.
        """
        class_name = class_name.strip().upper()
        method_name = method_name.strip().upper()

        try:
            backend = await get_backend(session=session, agent_id=agent_id, tool_name="sap_se24_edit")
        except ValueError as exc:
            return SE24EditResult.failure(
                error=f"Session error: {exc}",
                class_name=class_name,
                method_name=method_name,
                backup_source="",
                activated=False,
            )

        # Resolved outside the broad except below: an unsupported language must reach the caller as such
        t = lang.current("sap_se24_edit")

        try:
            return await _edit_check_activate_method(backend, class_name, method_name, new_source, t)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.exception("SE24 edit failed for %s->%s", class_name, method_name)
            return SE24EditResult.failure(
                error=f"Unexpected error: {exc}",
                class_name=class_name,
                method_name=method_name,
                backup_source="",
                activated=False,
            )
