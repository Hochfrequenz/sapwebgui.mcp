"""SM37, SLG1 and ST22 type dates in the date format of the SAP user, not in the one of the logon language (#42).

The Web GUI backend reads the format off the pre-filled date field (``resolve_user_date_format``); the language pack's
``date_format`` is only the fallback. The pack used here is DE (``DD.MM.YYYY``), the user's format is ``YYYY-MM-DD``.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sapwebguimcp import lang
from sapwebguimcp.tools.slg1_tools import _slg1_lookup
from sapwebguimcp.tools.sm37_tools import _fill_selection_screen
from sapwebguimcp.tools.st22_tools import _fill_date_field

_USER_FORMAT = "%Y-%m-%d"


def _backend(shown: str | None = "2026-10-07", calls: list[str] | None = None) -> MagicMock:
    """A fake Web GUI backend whose date field shows *shown*; *calls* records the order of reads and fills."""
    order = calls if calls is not None else []

    async def _read(_labels: Any) -> str | None:
        order.append("read")
        return shown

    async def _fill(_label: str, _value: str) -> None:
        order.append("fill")

    backend = MagicMock()
    backend.cached_date_format = AsyncMock(return_value=None)
    backend.cache_date_format = AsyncMock()
    backend.read_field_text = AsyncMock(side_effect=_read)
    backend.fill_field = AsyncMock(side_effect=_fill)
    backend.wait_for_ready = AsyncMock()
    return backend


async def _ensure_ok(_backend: Any, _target: Any) -> Any:
    return SimpleNamespace(success=True, error=None, warnings=[])


@pytest.mark.anyio
async def test_sm37_types_the_dates_in_the_user_format_read_before_the_first_fill() -> None:
    order: list[str] = []
    backend = _backend(calls=order)
    t = lang.view_for("DE")
    with patch("sapwebguimcp.tools.sm37_tools.ensure_screen_state", _ensure_ok):
        errors = await _fill_selection_screen(backend, t, "*", None, None, "2026-10-01", "2026-10-08")
    assert errors == []
    assert [call.args[1] for call in backend.fill_field.await_args_list] == ["2026-10-01", "2026-10-08"]
    assert order == ["read", "fill", "fill"]
    labels = backend.read_field_text.await_args.args[0]
    assert set(t.sm37.from_date) <= set(labels)
    backend.cache_date_format.assert_awaited_once_with(_USER_FORMAT)


@pytest.mark.anyio
async def test_sm37_without_dates_does_not_read_a_field() -> None:
    backend = _backend()
    t = lang.view_for("DE")
    with patch("sapwebguimcp.tools.sm37_tools.ensure_screen_state", _ensure_ok):
        await _fill_selection_screen(backend, t, "*", None, None, None, None)
    backend.read_field_text.assert_not_awaited()
    backend.fill_field.assert_not_awaited()


@pytest.mark.anyio
async def test_slg1_types_the_dates_in_the_user_format() -> None:
    backend = _backend()
    backend.enter_transaction = AsyncMock(return_value=SimpleNamespace(success=True, error=None))
    backend.fill_form = AsyncMock(return_value=SimpleNamespace(not_found=[], errors=[]))
    backend.press_key = AsyncMock()
    backend.get_snapshot = AsyncMock(return_value="")
    t = lang.view_for("DE")
    with patch("sapwebguimcp.tools.slg1_tools.is_slg1_no_results", return_value=True):
        await _slg1_lookup(backend, t, "*", None, None, "2026-10-01", "2026-10-08")
    typed = {label: value for call in backend.fill_form.await_args_list for label, value in call.args[0].items()}
    assert typed[t.slg1.from_datetime.variants[0]] == "2026-10-01"
    assert typed[t.slg1.to_datetime.variants[0]] == "2026-10-08"
    labels = backend.read_field_text.await_args.args[0]
    assert set(t.slg1.from_datetime) <= set(labels)
    backend.cache_date_format.assert_awaited_once_with(_USER_FORMAT)


@pytest.mark.anyio
async def test_slg1_without_dates_does_not_read_a_field() -> None:
    backend = _backend()
    backend.enter_transaction = AsyncMock(return_value=SimpleNamespace(success=True, error=None))
    backend.fill_form = AsyncMock(return_value=SimpleNamespace(not_found=[], errors=[]))
    backend.press_key = AsyncMock()
    backend.get_snapshot = AsyncMock(return_value="")
    t = lang.view_for("DE")
    with patch("sapwebguimcp.tools.slg1_tools.is_slg1_no_results", return_value=True):
        await _slg1_lookup(backend, t, "*")
    backend.read_field_text.assert_not_awaited()


@pytest.mark.anyio
async def test_st22_types_the_date_in_the_user_format() -> None:
    backend = _backend()
    t = lang.view_for("DE")
    assert await _fill_date_field(backend, t, "2026-10-01") is None
    assert backend.fill_field.await_args.args[1] == "2026-10-01"
    labels = backend.read_field_text.await_args.args[0]
    assert set(t.st22.date_field) <= set(labels)
    backend.cache_date_format.assert_awaited_once_with(_USER_FORMAT)


@pytest.mark.anyio
async def test_st22_falls_back_to_the_language_format_when_the_field_cannot_be_read(
    caplog: pytest.LogCaptureFixture,
) -> None:
    backend = _backend(shown=None)
    t = lang.view_for("DE")
    with caplog.at_level(logging.WARNING):
        assert await _fill_date_field(backend, t, "2026-10-01") is None
    assert backend.fill_field.await_args.args[1] == "01.10.2026"
    assert "falling back" in caplog.text
    backend.cache_date_format.assert_not_awaited()


@pytest.mark.anyio
async def test_st22_rejects_an_invalid_date_without_reading_the_field() -> None:
    backend = _backend()
    t = lang.view_for("DE")
    error = await _fill_date_field(backend, t, "01.10.2026")
    assert error is not None
    assert "Invalid date format" in error
    backend.read_field_text.assert_not_awaited()
    backend.fill_field.assert_not_awaited()
