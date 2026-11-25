"""Popup title and type of ``check_popup`` (#102): keywords on the language packs, read through ``lang.universal()``."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from sapwebguimcp import lang
from sapwebguimcp.backend.webgui.backend import WebGuiBackend, _classify_popup
from sapwebguimcp.models import PopupType

ERROR, INFO, CONFIRM, UNKNOWN = PopupType.ERROR, PopupType.INFO, PopupType.CONFIRM, PopupType.UNKNOWN


@pytest.fixture(params=[None, "XX", "DE", "EN"], ids=["no-session", "unsupported", "DE", "EN"])
def any_session(request: pytest.FixtureRequest) -> Any:
    """Every session state the universal sections must work in."""
    with lang.use(request.param):
        yield request.param


@pytest.mark.usefixtures("any_session")
@pytest.mark.parametrize(
    ("title", "message", "expected"),
    [
        ("Error in Object Editing", "", ERROR),
        ("", "Fehler beim Sichern", ERROR),
        ("Errore", "", ERROR),
        ("Information", "", INFO),
        ("Hinweis", "", INFO),
        ("Informazione", "", INFO),
        ("Bestätigung", "", CONFIRM),
        ("Confirm", "", CONFIRM),
        ("Confermare", "", CONFIRM),
        ("Beenden", "Beenden", UNKNOWN),
        ("Exit", "Exit", UNKNOWN),
        # The confirm keywords match whole words only: "No" in "Unknown" / "Note", "Ja" in "Jahr".
        ("Unknown object", "Note", UNKNOWN),
        ("Jahr", "", UNKNOWN),
        ("", "Daten sichern? Ja", CONFIRM),
    ],
)
def test_classify_popup_in_every_language(title: str, message: str, expected: PopupType) -> None:
    assert _classify_popup(title, message) is expected


def test_error_wins_over_confirm() -> None:
    assert _classify_popup("Confirm", "Error while saving") is PopupType.ERROR


def _backend(result: dict[str, Any]) -> WebGuiBackend:
    page = MagicMock()
    page.evaluate = AsyncMock(return_value=result)
    return WebGuiBackend(page)


@pytest.mark.anyio
async def test_check_popup_returns_title_and_type() -> None:
    backend = _backend(
        {
            "title": "Error in Object Editing",
            "message": "Error in Object Editing",
            "buttons": [],
            "close_button_id": None,
        }
    )
    popup = await backend.check_popup()
    assert popup is not None
    assert popup.title == "Error in Object Editing"
    assert popup.popup_type is PopupType.ERROR
    assert popup.message == "Error in Object Editing"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "extra", [{}, {"title": None}, {"title": ""}, {"title": "   "}], ids=["absent", "null", "empty", "blank"]
)
async def test_check_popup_without_title(extra: dict[str, Any]) -> None:
    """No header title: ``title`` is ``None`` (never ``""``) and the type comes from the message alone."""
    popup = await _backend({"message": "Save changes?", "buttons": [], "close_button_id": None, **extra}).check_popup()
    assert popup is not None
    assert popup.title is None
    assert popup.popup_type is PopupType.UNKNOWN
    assert popup.message == "Save changes?"
