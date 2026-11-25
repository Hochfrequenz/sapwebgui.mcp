"""Tests for WebGuiBackend helper functions."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sapwebguimcp.backend.webgui.backend import WebGuiBackend, _parse_toolbar_note
from sapwebguimcp.backend.webgui.models.session_registry import SessionRegistry
from sapwebguimcp.backend.webgui.utils import escape_css_selector


def test_parse_toolbar_note_success_de() -> None:
    """German success note should be parsed correctly."""
    snapshot = 'toolbar\n  note "Erfolgreich Meldungsleiste keine Syntaxfehler gefunden"'
    ok, msg = _parse_toolbar_note(snapshot)
    assert ok is True
    assert "keine Syntaxfehler" in msg


def test_parse_toolbar_note_success_en() -> None:
    """English success note should be parsed correctly."""
    snapshot = 'toolbar\n  note "Success Message Bar No syntax errors found"'
    ok, msg = _parse_toolbar_note(snapshot)
    assert ok is True
    assert "No syntax errors" in msg


def test_parse_toolbar_note_error_de() -> None:
    """German error note should be parsed correctly."""
    snapshot = 'toolbar\n  note "Fehler Meldungsleiste Syntaxfehler in Zeile 10"'
    ok, msg = _parse_toolbar_note(snapshot)
    assert ok is False
    assert "Syntaxfehler" in msg


def test_parse_toolbar_note_no_note() -> None:
    """Missing note should return failure."""
    ok, msg = _parse_toolbar_note("toolbar\n  heading 'Test'")
    assert ok is False
    assert "No status message" in msg


def test_escape_css_selector_special_chars() -> None:
    """SAP IDs with colons and brackets should be escaped."""
    assert escape_css_selector("#M0:48::btn[5]") == r"#M0\:48\:\:btn\[5\]"


def test_escape_css_selector_already_escaped() -> None:
    """Already-escaped selectors should not be double-escaped."""
    selector = r"#M0\:48\:\:btn\[5\]"
    assert escape_css_selector(selector) == selector


def test_escape_css_selector_no_special_chars() -> None:
    """Simple IDs should pass through unchanged."""
    assert escape_css_selector("#simple-id") == "#simple-id"


def test_escape_css_selector_partially_escaped() -> None:
    """Partially-escaped selectors should only escape the unescaped chars."""
    assert escape_css_selector(r"#M0\:48::btn[5]") == r"#M0\:48\:\:btn\[5\]"


def test_escape_css_selector_empty() -> None:
    """Empty selector should pass through."""
    assert escape_css_selector("") == ""


def _backend_with_registry(registered: bool) -> tuple[WebGuiBackend, SessionRegistry, str | None]:
    page = MagicMock()
    page.is_closed.return_value = False
    registry = SessionRegistry()
    session = registry.register(page) if registered else None
    return WebGuiBackend(page), registry, session


@pytest.mark.anyio
async def test_cache_date_format_round_trips_per_session() -> None:
    backend, registry, session = _backend_with_registry(True)
    with patch.object(WebGuiBackend, "_get_registry", new=AsyncMock(return_value=registry)):
        assert await backend.cached_date_format() is None
        await backend.cache_date_format("%Y-%m-%d")
        assert await backend.cached_date_format() == "%Y-%m-%d"
    assert session is not None
    assert registry.date_format_of(session) == "%Y-%m-%d"


@pytest.mark.anyio
async def test_date_format_cache_of_an_unregistered_page_is_inert() -> None:
    backend, registry, _ = _backend_with_registry(False)
    with patch.object(WebGuiBackend, "_get_registry", new=AsyncMock(return_value=registry)):
        await backend.cache_date_format("%Y-%m-%d")
        assert await backend.cached_date_format() is None


@pytest.mark.anyio
async def test_read_field_text_passes_the_labels_and_returns_the_value() -> None:
    backend, _, _ = _backend_with_registry(False)
    evaluate = AsyncMock(return_value="x")
    backend._page.evaluate = evaluate  # type: ignore[method-assign]  # pylint: disable=protected-access
    assert await backend.read_field_text(["A", "B"]) == "x"
    assert evaluate.await_args is not None
    assert evaluate.await_args.args[1] == {"labels": ["A", "B"]}


@pytest.mark.anyio
@pytest.mark.parametrize("returned", [None, 5, {"a": 1}])
async def test_read_field_text_without_a_string_is_none(returned: object) -> None:
    backend, _, _ = _backend_with_registry(False)
    backend._page.evaluate = AsyncMock(return_value=returned)  # type: ignore[method-assign]  # pylint: disable=protected-access
    assert await backend.read_field_text(["A"]) is None
