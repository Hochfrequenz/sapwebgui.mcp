"""A requested selection field that cannot be filled fails the lookup before F8 (issue #98).

Pressing F8 with a field left at its default would run SAP's default selection and return a result that does not match
the requested filters. The lookup must fail instead.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sapwebguimcp import lang
from sapwebguimcp.lang.schema import JobStatus
from sapwebguimcp.models.sap_results import FieldFillError, FillFormResult
from sapwebguimcp.tools.slg1_tools import _slg1_lookup
from sapwebguimcp.tools.sm37_tools import _execute_sm37_lookup

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
    backend = _backend({label: FillFormResult(not_found=[label]) for label in t.slg1.log_subobject})

    result = await _slg1_lookup(backend, t, "OBJ", subobject="SUB", external_id="EXT")

    assert result.success is False
    assert result.error == _PREFIX + "subobject"
    assert result.logs == []
    backend.press_key.assert_not_awaited()


@pytest.mark.anyio
async def test_slg1_names_every_unfilled_field_in_parameter_order() -> None:
    not_filled = {
        **{label: FillFormResult(not_found=[label]) for label in t.slg1.log_subobject},
        **{label: FillFormResult(not_found=[label]) for label in t.slg1.to_datetime},
    }
    backend = _backend(not_filled)

    result = await _slg1_lookup(backend, t, "OBJ", subobject="SUB", to_date="2026-01-31")

    assert result.success is False
    assert result.error is not None
    assert result.error.endswith(": subobject, to_date")
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


# ---------------------------------------------------------------------------
# SM37
# ---------------------------------------------------------------------------

_SM37_PREFIX = "Could not apply the filter(s) on the SM37 selection screen: "


def _sm37_backend() -> MagicMock:
    """A backend for the SM37 workflow whose F8 shows the "no jobs" message."""
    backend = MagicMock()
    backend.enter_transaction = AsyncMock(return_value=SimpleNamespace(success=True, error=None))
    backend.wait_for_ready = AsyncMock()
    backend.press_key = AsyncMock()
    backend.fill_field = AsyncMock()
    backend.get_snapshot = AsyncMock(return_value=t.sm37.no_jobs.variants[0])
    return backend


def _screen_state(not_applied: list[str], *, success: bool = True, error: str | None = None) -> Any:
    """A fake ``ensure_screen_state`` that answers with ``not_applied``."""

    async def fake(_backend: Any, _target: Any) -> Any:
        return SimpleNamespace(success=success, error=error, warnings=[], not_applied=not_applied)

    return fake


async def _sm37(
    backend: MagicMock,
    state: Any,
    username: str | None = "ME",
    statuses: list[str] | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> Any:
    with patch("sapwebguimcp.tools.sm37_tools.ensure_screen_state", state):
        return await _execute_sm37_lookup(backend, t, "JOB*", username, statuses, from_date, to_date, False)


@pytest.mark.anyio
async def test_sm37_fails_before_f8_when_the_user_field_is_missing() -> None:
    backend = _sm37_backend()

    result = await _sm37(backend, _screen_state(list(t.sm37.user_name)))

    assert result.success is False
    assert result.error == _SM37_PREFIX + "username"
    assert result.jobs == []
    assert result.job_count == 0
    assert result.filters_applied == {}
    backend.press_key.assert_not_awaited()


@pytest.mark.anyio
async def test_sm37_other_language_label_missing_is_not_a_failure() -> None:
    """Guard: a label of another language or release is not on the screen; the one that is, was applied."""
    dropped_first = [
        label for text in (t.sm37.job_name, t.sm37.user_name, *t.sm37.status.values()) for label in text.variants[1:]
    ]
    assert dropped_first  # not vacuous: some variants really are reported as not applied
    backend = _sm37_backend()

    result = await _sm37(backend, _screen_state(dropped_first), statuses=["finished"])

    assert result.success is True
    backend.press_key.assert_awaited_once_with("F8")


@pytest.mark.anyio
async def test_sm37_status_checkbox_missing_fails_when_status_given() -> None:
    backend = _sm37_backend()

    result = await _sm37(backend, _screen_state(list(t.sm37.status[JobStatus.CANCELED])), statuses=["finished"])

    assert result.success is False
    assert result.error is not None
    assert result.error.endswith(": status")
    backend.press_key.assert_not_awaited()


@pytest.mark.anyio
async def test_sm37_unrequested_status_and_user_do_not_fail() -> None:
    """Guard: with no status and no username requested, missing boxes and fields are no filter that failed."""
    not_applied = [*t.sm37.status[JobStatus.CANCELED], *t.sm37.user_name]
    backend = _sm37_backend()

    result = await _sm37(backend, _screen_state(not_applied), username=None, statuses=None)

    assert result.success is True
    backend.press_key.assert_awaited_once_with("F8")


@pytest.mark.anyio
async def test_sm37_date_field_missing_fails() -> None:
    backend = _sm37_backend()
    backend.fill_field = AsyncMock(side_effect=ValueError)

    result = await _sm37(backend, _screen_state([]), from_date="2026-01-01")

    assert result.success is False
    assert result.error is not None
    assert result.error.endswith(": from_date")
    backend.press_key.assert_not_awaited()


@pytest.mark.anyio
async def test_sm37_to_date_field_missing_fails() -> None:
    backend = _sm37_backend()
    backend.fill_field = AsyncMock(side_effect=ValueError)

    result = await _sm37(backend, _screen_state([]), to_date="2026-01-31")

    assert result.success is False
    assert result.error is not None
    assert result.error.endswith(": to_date")
    backend.press_key.assert_not_awaited()


@pytest.mark.anyio
async def test_sm37_screen_state_failure_fails_before_f8() -> None:
    backend = _sm37_backend()

    result = await _sm37(backend, _screen_state([], success=False, error="Ambiguous labels"))

    assert result.success is False
    assert result.error == _SM37_PREFIX + "job_name, username (Ambiguous labels)"
    backend.press_key.assert_not_awaited()


@pytest.mark.anyio
async def test_sm37_user_name_is_handed_over_upper_case() -> None:
    """SAP user names are upper case and ensure_screen_state verifies with an exact comparison."""
    targets: list[Any] = []

    async def record(_backend: Any, target: Any) -> Any:
        targets.append(target)
        return SimpleNamespace(success=True, error=None, warnings=[], not_applied=[])

    backend = _sm37_backend()

    result = await _sm37(backend, record, username="jdoe")

    assert result.success is True
    assert result.filters_applied["username"] == "jdoe"
    (target,) = targets
    assert all(target.fields[label] == "JDOE" for label in t.sm37.user_name)
