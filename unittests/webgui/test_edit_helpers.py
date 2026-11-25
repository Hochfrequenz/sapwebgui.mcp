"""Tests for the shared SE38/SE24/SE37 edit helpers (#103)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sapwebguimcp.models import ClosePopupResult, PopupButton, PopupInfo, SE38EditResult, TransactionResult
from sapwebguimcp.tools import edit_helpers
from sapwebguimcp.tools.edit_helpers import describe_failed_replace, finish_edit, leave_editor


def _backend(
    popups: list[PopupInfo | None] | None = None,
    transaction: TransactionResult | None = None,
    dismiss: ClosePopupResult | None = None,
) -> MagicMock:
    backend = MagicMock()
    backend.check_popup = AsyncMock(side_effect=popups if popups is not None else [None, None])
    backend.enter_transaction = AsyncMock(return_value=transaction or TransactionResult(success=True, tcode="/n"))
    backend.dismiss_popup = AsyncMock(return_value=dismiss or ClosePopupResult(success=True, popup_closed=True))
    return backend


def _popup(message: str = "Save changes?", close_button_id: str | None = "close-x") -> PopupInfo:
    return PopupInfo(
        message=message,
        buttons=[PopupButton(label="Ja"), PopupButton(label="Nein")],
        close_button_id=close_button_id,
    )


@pytest.mark.anyio
async def test_leave_editor_without_popup_ends_the_transaction() -> None:
    backend = _backend()

    assert await leave_editor(backend) is None

    backend.enter_transaction.assert_awaited_once_with("/n")
    backend.dismiss_popup.assert_not_awaited()


@pytest.mark.anyio
async def test_leave_editor_closes_open_popup_with_close_control() -> None:
    backend = _backend(popups=[_popup(), None])

    assert await leave_editor(backend) is None

    backend.dismiss_popup.assert_awaited_once_with(use_close_button=True)
    backend.enter_transaction.assert_awaited_once_with("/n")


@pytest.mark.anyio
async def test_leave_editor_popup_without_close_control() -> None:
    backend = _backend(popups=[_popup(close_button_id=None)])

    reason = await leave_editor(backend)

    assert isinstance(reason, str)
    assert "Save changes?" in reason
    backend.enter_transaction.assert_not_awaited()
    backend.dismiss_popup.assert_not_awaited()


@pytest.mark.anyio
async def test_leave_editor_reports_popup_that_stays_open() -> None:
    backend = _backend(popups=[_popup()], dismiss=ClosePopupResult(success=True, popup_closed=False))

    reason = await leave_editor(backend)

    assert isinstance(reason, str)
    backend.enter_transaction.assert_not_awaited()


@pytest.mark.anyio
async def test_leave_editor_reports_failed_transaction() -> None:
    backend = _backend(transaction=TransactionResult.failure("boom", tcode="/n"))

    reason = await leave_editor(backend)

    assert reason is not None
    assert "boom" in reason


@pytest.mark.anyio
async def test_leave_editor_reports_popup_after_leaving() -> None:
    backend = _backend(popups=[None, _popup("Save changes?")])

    reason = await leave_editor(backend)

    assert reason is not None
    assert "Save changes?" in reason
    backend.dismiss_popup.assert_awaited_once_with(use_close_button=True)


@pytest.mark.anyio
async def test_leave_editor_never_raises() -> None:
    backend = _backend()
    backend.enter_transaction = AsyncMock(side_effect=RuntimeError("page closed"))

    reason = await leave_editor(backend)

    assert reason is not None
    assert "page closed" in reason


@pytest.mark.anyio
async def test_describe_failed_replace_is_tool_neutral() -> None:
    backend = MagicMock()
    backend.replace_editor_source = AsyncMock(return_value=False)

    text = await describe_failed_replace(backend, "REPORT zfoo.")

    assert "SE38" not in text
    assert "Leave SE38" not in text
    assert "leaves the editor without saving" in text
    assert "WITHOUT saving" in text


@pytest.mark.anyio
async def test_finish_edit_appends_warning_only_on_failure() -> None:
    backend = MagicMock()
    result = SE38EditResult(success=True, program_name="ZFOO", backup_source="", check_messages=["ok"], activated=True)

    with patch.object(edit_helpers, "leave_editor", AsyncMock(return_value="x")):
        returned = await finish_edit(backend, result)

    assert returned is result
    assert result.check_messages[-1].startswith("WARNING: could not leave the editor (x)")
    assert result.success is True

    unchanged = SE38EditResult(
        success=True, program_name="ZFOO", backup_source="", check_messages=["ok"], activated=True
    )
    with patch.object(edit_helpers, "leave_editor", AsyncMock(return_value=None)):
        await finish_edit(backend, unchanged)

    assert unchanged.check_messages == ["ok"]
