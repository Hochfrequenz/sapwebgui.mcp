"""Tests for SE38 edit tool."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from sapwebguimcp import lang
from sapwebguimcp.models import TransactionResult
from sapwebguimcp.models.se38_edit_models import SE38EditResult


def test_se38_edit_result_success() -> None:
    """Test successful SE38EditResult creation."""
    from sapwebguimcp.models.se38_edit_models import SE38EditResult

    result = SE38EditResult(
        success=True,
        program_name="ZTEST_MCP_EDIT",
        backup_source="REPORT ZTEST_MCP_EDIT.\nWRITE 'OLD'.",
        check_messages=["No syntax errors found"],
        activated=True,
    )
    assert result.success is True
    assert result.program_name == "ZTEST_MCP_EDIT"
    assert result.backup_source == "REPORT ZTEST_MCP_EDIT.\nWRITE 'OLD'."
    assert result.activated is True
    assert result.error is None


def test_se38_edit_result_failure() -> None:
    """Test failed SE38EditResult creation via factory."""
    from sapwebguimcp.models.se38_edit_models import SE38EditResult

    result = SE38EditResult.failure(
        error="Syntax error in line 3",
        program_name="ZTEST_MCP_EDIT",
        backup_source="REPORT ZTEST_MCP_EDIT.\nWRITE 'OLD'.",
        check_messages=["Syntax error: unexpected token"],
        activated=False,
    )
    assert result.success is False
    assert result.error == "Syntax error in line 3"
    assert result.activated is False


def test_se38_edit_result_validation_error() -> None:
    """Test that success=True with error raises ValidationError."""
    from sapwebguimcp.models.se38_edit_models import SE38EditResult

    with pytest.raises(ValidationError):
        SE38EditResult(
            success=True,
            error="This should not be set",
            program_name="ZTEST",
            backup_source="",
            check_messages=[],
            activated=False,
        )


class TestParseStatusNote:
    """Tests for parsing status bar notes from ARIA snapshots."""

    def test_parse_check_success_de(self) -> None:
        from sapwebguimcp.backend.webgui.backend import _parse_toolbar_note as parse_toolbar_note

        snapshot = '- note "Erfolgreich Meldungsleiste Es wurden keine Syntaxfehler in Report ZTEST_MCP_EDIT gefunden"'
        success, message = parse_toolbar_note(snapshot)
        assert success is True
        assert "keine Syntaxfehler" in message or "No syntax errors" in message

    def test_parse_activate_success_de(self) -> None:
        from sapwebguimcp.backend.webgui.backend import _parse_toolbar_note as parse_toolbar_note

        snapshot = '- note "Erfolgreich Meldungsleiste Aktives Objekt wurde generiert"'
        success, message = parse_toolbar_note(snapshot)
        assert success is True
        assert "generiert" in message or "generated" in message

    def test_parse_check_failure_de(self) -> None:
        from sapwebguimcp.backend.webgui.backend import _parse_toolbar_note as parse_toolbar_note

        snapshot = '- note "Fehler Meldungsleiste Syntaxfehler in Zeile 3"'
        success, message = parse_toolbar_note(snapshot)
        assert success is False
        assert "Syntaxfehler" in message

    def test_parse_check_success_en(self) -> None:
        from sapwebguimcp.backend.webgui.backend import _parse_toolbar_note as parse_toolbar_note

        snapshot = '- note "Success Message Bar No syntax errors found in Report ZTEST_MCP_EDIT"'
        success, message = parse_toolbar_note(snapshot)
        assert success is True
        assert "No syntax errors" in message

    def test_parse_activate_success_en(self) -> None:
        from sapwebguimcp.backend.webgui.backend import _parse_toolbar_note as parse_toolbar_note

        snapshot = '- note "Success Message Bar Object activated"'
        success, message = parse_toolbar_note(snapshot)
        assert success is True
        assert "Object activated" in message

    def test_parse_check_failure_en(self) -> None:
        from sapwebguimcp.backend.webgui.backend import _parse_toolbar_note as parse_toolbar_note

        snapshot = '- note "Error Message Bar Specify a program name"'
        success, message = parse_toolbar_note(snapshot)
        assert success is False
        assert "Specify a program name" in message

    def test_parse_no_note(self) -> None:
        from sapwebguimcp.backend.webgui.backend import _parse_toolbar_note as parse_toolbar_note

        snapshot = "- button 'Aktivieren'"
        success, message = parse_toolbar_note(snapshot)
        assert success is False
        assert message  # should have a default message


@pytest.mark.anyio
async def test_se38_edit_tool_is_registered() -> None:
    """Test that register_se38_edit_tools adds the tool to a FastMCP instance."""
    from fastmcp import FastMCP

    from sapwebguimcp.tools.se38_edit_tools import register_se38_edit_tools

    mcp = FastMCP("test")
    register_se38_edit_tools(mcp)

    tool = await mcp.get_tool("sap_se38_edit")
    assert tool is not None, "sap_se38_edit tool not found after registration"


def _leaving_backend() -> MagicMock:
    """A backend whose editor can be left: no popup is open and ``/n`` succeeds."""
    backend = MagicMock()
    backend.check_popup = AsyncMock(return_value=None)
    backend.enter_transaction = AsyncMock(return_value=TransactionResult(tcode="/n"))
    return backend


async def _call_se38_edit(backend: MagicMock, core: AsyncMock) -> SE38EditResult:
    """Call the registered ``sap_se38_edit`` with the backend and the core edit function replaced."""
    from fastmcp import FastMCP

    from sapwebguimcp.tools.se38_edit_tools import register_se38_edit_tools

    mcp = FastMCP("test")
    register_se38_edit_tools(mcp)
    tool = await mcp.get_tool("sap_se38_edit")
    with (
        patch("sapwebguimcp.tools.se38_edit_tools.get_backend", AsyncMock(return_value=backend)),
        patch("sapwebguimcp.tools.se38_edit_tools._edit_check_activate", core),
        lang.use("DE"),
    ):
        result = await tool.fn(program_name="ZTEST", new_source="x")
    assert isinstance(result, SE38EditResult)
    return result


@pytest.mark.anyio
async def test_se38_edit_leaves_editor_after_success() -> None:
    backend = _leaving_backend()
    edit = SE38EditResult(
        success=True, program_name="ZTEST", backup_source="old", check_messages=["ok"], activated=True
    )

    result = await _call_se38_edit(backend, AsyncMock(return_value=edit))

    backend.enter_transaction.assert_awaited_once_with("/n")
    assert result is edit
    assert result.success is True
    assert result.check_messages == ["ok"]


@pytest.mark.anyio
async def test_se38_edit_leaves_editor_after_failure() -> None:
    backend = _leaving_backend()
    edit = SE38EditResult.failure(
        error="Check/activate failed", program_name="ZTEST", backup_source="old", activated=False
    )

    result = await _call_se38_edit(backend, AsyncMock(return_value=edit))

    backend.enter_transaction.assert_awaited_once_with("/n")
    assert result.success is False
    assert result.error == "Check/activate failed"


@pytest.mark.anyio
async def test_se38_edit_leaves_editor_after_unexpected_error() -> None:
    backend = _leaving_backend()

    result = await _call_se38_edit(backend, AsyncMock(side_effect=RuntimeError("x")))

    backend.enter_transaction.assert_awaited_once_with("/n")
    assert result.success is False
    assert result.error is not None
    assert "Unexpected error: x" in result.error


@pytest.mark.anyio
async def test_se38_edit_reports_when_leaving_the_editor_failed() -> None:
    backend = _leaving_backend()
    backend.enter_transaction = AsyncMock(return_value=TransactionResult.failure("boom", tcode="/n"))
    edit = SE38EditResult(
        success=True, program_name="ZTEST", backup_source="old", check_messages=["ok"], activated=True
    )

    result = await _call_se38_edit(backend, AsyncMock(return_value=edit))

    assert result.success is True
    assert result.check_messages[0] == "ok"
    assert result.check_messages[-1].startswith("WARNING: could not leave the editor")


@pytest.mark.anyio
async def test_se38_edit_description_states_when_the_editor_is_left() -> None:
    """The description says the editor is left on finish or failure, and not on cancellation."""
    from fastmcp import FastMCP

    from sapwebguimcp.tools.se38_edit_tools import register_se38_edit_tools

    mcp = FastMCP("test")
    register_se38_edit_tools(mcp)
    tool = await mcp.get_tool("sap_se38_edit")
    assert tool.description is not None
    assert "When it finishes or fails, the tool leaves the editor without saving (/n)" in tool.description
    assert "not when the call is cancelled" in tool.description


@pytest.mark.anyio
async def test_se38_edit_failed_revert_hint_points_at_backup_source() -> None:
    """When the auto-revert cannot replace the source, the hint says how to recover."""
    from sapwebguimcp.models.base import CheckActivateResult
    from sapwebguimcp.tools.se38_edit_tools import _edit_check_activate

    backend = MagicMock()
    backend.read_editor_source = AsyncMock(return_value="OLD")
    backend.replace_editor_source = AsyncMock(side_effect=[True, False])
    backend.check_and_activate = AsyncMock(
        return_value=CheckActivateResult(
            success=False, error="Check failed", messages=["Check: error"], activated=False
        )
    )
    with (
        patch("sapwebguimcp.tools.se38_edit_tools._navigate_and_open_editor", AsyncMock(return_value=None)),
        lang.use("DE"),
    ):
        t = lang.current("test")
        result = await _edit_check_activate(backend, "ZTEST", "NEW", t)
    assert result.success is False
    assert result.error is not None
    assert "re-apply backup_source" in result.error
    assert "Manual intervention" not in result.error


@pytest.mark.anyio
async def test_se38_edit_revert_not_activated_says_the_restored_source_was_not_saved() -> None:
    """The original source is written back but fails its own check: it is never saved, and
    leaving the editor discards it, so the result must not claim the source was reverted."""
    from sapwebguimcp.models.base import CheckActivateResult
    from sapwebguimcp.tools.se38_edit_tools import _edit_check_activate

    backend = MagicMock()
    backend.read_editor_source = AsyncMock(return_value="OLD")
    backend.replace_editor_source = AsyncMock(side_effect=[True, True])
    backend.check_and_activate = AsyncMock(
        return_value=CheckActivateResult(
            success=False, error="Check failed", messages=["Check: error"], activated=False
        )
    )
    with (
        patch("sapwebguimcp.tools.se38_edit_tools._navigate_and_open_editor", AsyncMock(return_value=None)),
        lang.use("DE"),
    ):
        t = lang.current("test")
        result = await _edit_check_activate(backend, "ZTEST", "NEW", t)
    assert result.success is False
    assert result.error is not None
    assert "Auto-reverted source" not in result.error
    assert "not saved" in result.error
    assert "re-apply backup_source" in result.error
