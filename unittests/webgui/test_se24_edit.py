"""Tests for SE24 edit tool."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from sapwebguimcp import lang
from sapwebguimcp.models import TransactionResult
from sapwebguimcp.models.se24_edit_models import SE24EditResult


def test_se24_edit_result_success() -> None:
    """Test successful SE24EditResult creation."""
    from sapwebguimcp.models.se24_edit_models import SE24EditResult

    result = SE24EditResult(
        success=True,
        class_name="ZCL_TEST_MCP_EDIT",
        method_name="DO_SOMETHING",
        backup_source="  METHOD do_something.\n  ENDMETHOD.",
        check_messages=["No syntax errors found"],
        activated=True,
    )
    assert result.success is True
    assert result.class_name == "ZCL_TEST_MCP_EDIT"
    assert result.method_name == "DO_SOMETHING"
    assert result.backup_source == "  METHOD do_something.\n  ENDMETHOD."
    assert result.activated is True
    assert result.error is None


def test_se24_edit_result_failure() -> None:
    """Test failed SE24EditResult creation via factory."""
    from sapwebguimcp.models.se24_edit_models import SE24EditResult

    result = SE24EditResult.failure(
        error="Syntax error in line 3",
        class_name="ZCL_TEST_MCP_EDIT",
        method_name="DO_SOMETHING",
        backup_source="  METHOD do_something.\n  ENDMETHOD.",
        check_messages=["Syntax error: unexpected token"],
        activated=False,
    )
    assert result.success is False
    assert result.error == "Syntax error in line 3"
    assert result.activated is False


def test_se24_edit_result_validation_error() -> None:
    """Test that success=True with error raises ValidationError."""
    from sapwebguimcp.models.se24_edit_models import SE24EditResult

    with pytest.raises(ValidationError):
        SE24EditResult(
            success=True,
            error="This should not be set",
            class_name="ZCL_TEST",
            method_name="DO_SOMETHING",
            backup_source="",
            check_messages=[],
            activated=False,
        )


class TestParseStatusNote:
    """Tests for parsing status bar notes — shared with SE38/SE37 but verified for SE24 context."""

    def test_parse_check_success_de(self) -> None:
        from sapwebguimcp.backend.webgui.backend import _parse_toolbar_note as parse_toolbar_note

        snapshot = (
            '- note "Erfolgreich Meldungsleiste Es wurden keine Syntaxfehler in Klasse ZCL_TEST_MCP_EDIT gefunden"'
        )
        success, message = parse_toolbar_note(snapshot)
        assert success is True
        assert "keine Syntaxfehler" in message

    def test_parse_activate_success_de(self) -> None:
        from sapwebguimcp.backend.webgui.backend import _parse_toolbar_note as parse_toolbar_note

        snapshot = '- note "Erfolgreich Meldungsleiste Objekt wurde aktiviert"'
        success, message = parse_toolbar_note(snapshot)
        assert success is True

    def test_parse_check_failure_de(self) -> None:
        from sapwebguimcp.backend.webgui.backend import _parse_toolbar_note as parse_toolbar_note

        snapshot = '- note "Fehler Meldungsleiste Syntaxfehler in Zeile 3"'
        success, message = parse_toolbar_note(snapshot)
        assert success is False
        assert "Syntaxfehler" in message

    def test_parse_check_success_en(self) -> None:
        from sapwebguimcp.backend.webgui.backend import _parse_toolbar_note as parse_toolbar_note

        snapshot = '- note "Success Message Bar No syntax errors found in Class ZCL_TEST_MCP_EDIT"'
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

        snapshot = '- note "Error Message Bar Syntax error in line 3"'
        success, message = parse_toolbar_note(snapshot)
        assert success is False

    def test_parse_no_note(self) -> None:
        from sapwebguimcp.backend.webgui.backend import _parse_toolbar_note as parse_toolbar_note

        snapshot = "- button 'Aktivieren'"
        success, message = parse_toolbar_note(snapshot)
        assert success is False
        assert message


@pytest.mark.anyio
async def test_se24_edit_tool_is_registered() -> None:
    """Test that register_se24_edit_tools adds the tool to a FastMCP instance."""
    from fastmcp import FastMCP

    from sapwebguimcp.tools.se24_edit_tools import register_se24_edit_tools

    mcp = FastMCP("test")
    register_se24_edit_tools(mcp)

    tool = await mcp.get_tool("sap_se24_edit")
    assert tool is not None, "sap_se24_edit tool not found after registration"


def _leaving_backend() -> MagicMock:
    """A backend whose editor can be left: no popup is open and ``/n`` succeeds."""
    backend = MagicMock()
    backend.check_popup = AsyncMock(return_value=None)
    backend.enter_transaction = AsyncMock(return_value=TransactionResult(tcode="/n"))
    return backend


async def _call_se24_edit(backend: MagicMock, core: AsyncMock) -> SE24EditResult:
    """Call the registered ``sap_se24_edit`` with the backend and the core edit function replaced."""
    from fastmcp import FastMCP

    from sapwebguimcp.tools.se24_edit_tools import register_se24_edit_tools

    mcp = FastMCP("test")
    register_se24_edit_tools(mcp)
    tool = await mcp.get_tool("sap_se24_edit")
    with (
        patch("sapwebguimcp.tools.se24_edit_tools.get_backend", AsyncMock(return_value=backend)),
        patch("sapwebguimcp.tools.se24_edit_tools._edit_check_activate_method", core),
        lang.use("DE"),
    ):
        result = await tool.fn(class_name="ZCL_T", method_name="M", new_source="x")
    assert isinstance(result, SE24EditResult)
    return result


@pytest.mark.anyio
async def test_se24_edit_leaves_editor_after_success() -> None:
    backend = _leaving_backend()
    edit = SE24EditResult(
        success=True,
        class_name="ZCL_T",
        method_name="M",
        backup_source="old",
        check_messages=["ok"],
        activated=True,
    )

    result = await _call_se24_edit(backend, AsyncMock(return_value=edit))

    backend.enter_transaction.assert_awaited_once_with("/n")
    assert result is edit
    assert result.success is True
    assert result.check_messages == ["ok"]


@pytest.mark.anyio
async def test_se24_edit_leaves_editor_after_failure() -> None:
    backend = _leaving_backend()
    edit = SE24EditResult.failure(
        error="Check/activate failed", class_name="ZCL_T", method_name="M", backup_source="old", activated=False
    )

    result = await _call_se24_edit(backend, AsyncMock(return_value=edit))

    backend.enter_transaction.assert_awaited_once_with("/n")
    assert result.success is False
    assert result.error == "Check/activate failed"


@pytest.mark.anyio
async def test_se24_edit_leaves_editor_after_unexpected_error() -> None:
    backend = _leaving_backend()

    result = await _call_se24_edit(backend, AsyncMock(side_effect=RuntimeError("x")))

    backend.enter_transaction.assert_awaited_once_with("/n")
    assert result.success is False
    assert result.error is not None
    assert "Unexpected error: x" in result.error


@pytest.mark.anyio
async def test_se24_edit_reports_when_leaving_the_editor_failed() -> None:
    backend = _leaving_backend()
    backend.enter_transaction = AsyncMock(return_value=TransactionResult.failure("boom", tcode="/n"))
    edit = SE24EditResult(
        success=True,
        class_name="ZCL_T",
        method_name="M",
        backup_source="old",
        check_messages=["ok"],
        activated=True,
    )

    result = await _call_se24_edit(backend, AsyncMock(return_value=edit))

    assert result.success is True
    assert result.check_messages[0] == "ok"
    assert result.check_messages[-1].startswith("WARNING: could not leave the editor")


@pytest.mark.anyio
async def test_se24_edit_description_states_when_the_editor_is_left() -> None:
    """The description says the editor is left on finish or failure, and not on cancellation."""
    from fastmcp import FastMCP

    from sapwebguimcp.tools.se24_edit_tools import register_se24_edit_tools

    mcp = FastMCP("test")
    register_se24_edit_tools(mcp)
    tool = await mcp.get_tool("sap_se24_edit")
    assert tool.description is not None
    assert "When it finishes or fails, the tool leaves the editor without saving (/n)" in tool.description
    assert "not when the call is cancelled" in tool.description


@pytest.mark.anyio
async def test_se24_edit_failed_revert_hint_points_at_backup_source() -> None:
    """When the auto-revert cannot replace the source, the hint says how to recover."""
    from sapwebguimcp.models.base import CheckActivateResult
    from sapwebguimcp.tools.se24_edit_tools import _edit_check_activate_method

    backend = MagicMock()
    backend.read_editor_source = AsyncMock(return_value="OLD")
    backend.replace_editor_source = AsyncMock(side_effect=[True, False])
    backend.check_and_activate = AsyncMock(
        return_value=CheckActivateResult(
            success=False, error="Check failed", messages=["Check: error"], activated=False
        )
    )
    with (
        patch("sapwebguimcp.tools.se24_edit_tools._navigate_to_method_editor", AsyncMock(return_value=None)),
        lang.use("DE"),
    ):
        t = lang.current("test")
        result = await _edit_check_activate_method(backend, "ZCL_TEST", "RUN", "NEW", t)
    assert result.success is False
    assert result.error is not None
    assert "re-apply backup_source" in result.error
    assert "Manual intervention" not in result.error
