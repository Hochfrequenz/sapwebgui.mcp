"""A requested selection field that cannot be filled fails the lookup before F8 (issue #98).

Pressing F8 with a field left at its default would run SAP's default selection and return a result that does not match
the requested filters. The lookup must fail instead.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from sapwebguimcp import lang
from sapwebguimcp.models.sap_results import FieldFillError, FillFormResult
from sapwebguimcp.tools.slg1_tools import _slg1_lookup

if TYPE_CHECKING:
    from collections.abc import Iterable

t = lang.view_for("EN")

_PREFIX = "Could not apply the filter(s) on the SLG1 selection screen: "


def _backend(fill_for: dict[str, Any]) -> MagicMock:
    """A backend whose ``fill_form`` answers with ``fill_for[label]`` and with a plain success for any other label."""

    async def fill_form(fields: dict[str, str]) -> Any:
        (label,) = fields
        if label in fill_for:
            return fill_for[label]
        return FillFormResult(filled=[label], not_found=[], errors=[])

    backend = MagicMock()
    backend.enter_transaction = AsyncMock(return_value=SimpleNamespace(success=True, error=None))
    backend.wait_for_ready = AsyncMock()
    backend.press_key = AsyncMock()
    backend.get_snapshot = AsyncMock(return_value="")
    backend.get_status_bar = AsyncMock(return_value=SimpleNamespace(type="none", message=""))
    backend.fill_form = AsyncMock(side_effect=fill_form)
    return backend


def _for_labels(labels: Iterable[str], result: Any) -> dict[str, Any]:
    return dict.fromkeys(labels, result)


@pytest.mark.anyio
async def test_slg1_fails_before_f8_when_a_field_cannot_be_filled() -> None:
    backend = _backend({label: SimpleNamespace(not_found=[label], errors=[]) for label in t.slg1.log_subobject})

    result = await _slg1_lookup(backend, t, "OBJ", subobject="SUB", external_id="EXT")

    assert result.success is False
    assert result.error == _PREFIX + "subobject"
    assert result.logs == []
    backend.press_key.assert_not_awaited()


@pytest.mark.anyio
async def test_slg1_fails_when_a_value_is_refused() -> None:
    refused = FillFormResult(errors=[FieldFillError(field="x", error="x")])
    backend = _backend(_for_labels(t.slg1.from_datetime, refused))

    result = await _slg1_lookup(backend, t, "OBJ", from_date="2026-01-01")

    assert result.success is False
    assert result.error is not None
    assert result.error.endswith(": from_date")
    backend.press_key.assert_not_awaited()


@pytest.mark.anyio
async def test_slg1_fails_when_the_fill_call_itself_fails() -> None:
    backend = _backend(_for_labels(t.slg1.log_object, FillFormResult.failure("boom")))

    result = await _slg1_lookup(backend, t, "OBJ")

    assert result.success is False
    assert result.error is not None
    assert result.error.endswith(": object")
    backend.press_key.assert_not_awaited()
