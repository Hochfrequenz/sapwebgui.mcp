"""press_key reads the screen only after the round trip of the key has finished (#79)."""

# pylint: disable=protected-access

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from sapwebguimcp.backend.webgui import backend as backend_module
from sapwebguimcp.backend.webgui.backend import WebGuiBackend

if TYPE_CHECKING:
    from collections.abc import Callable


class _FakePage:
    """A page whose title changes when the POST request of a key press finishes."""

    def __init__(self, *, round_trip: bool, delay_s: float = 0.05, from_iframe: bool = False) -> None:
        self.main_frame = object()
        self.from_iframe = from_iframe
        self.handlers: dict[str, list[Callable[[Any], None]]] = {}
        self.title_value = "before"
        self.round_trip = round_trip
        self.delay_s = delay_s
        self.keyboard = MagicMock()
        self.keyboard.press = AsyncMock(side_effect=self._press)
        self.bring_to_front = AsyncMock()
        self.wait_for_timeout = AsyncMock()
        self.wait_for_load_state = AsyncMock()
        self.evaluate = AsyncMock(return_value={"type": "S", "message": "done"})

    def on(self, event: str, handler: Callable[[Any], None]) -> None:
        self.handlers.setdefault(event, []).append(handler)

    def remove_listener(self, event: str, handler: Callable[[Any], None]) -> None:
        self.handlers[event].remove(handler)

    async def title(self) -> str:
        return self.title_value

    async def _press(self, _key: str) -> None:
        if not self.round_trip:
            return
        request = MagicMock()
        request.method = "POST"
        request.frame = object() if self.from_iframe else self.main_frame
        request.resource_type = "xhr"
        for handler in list(self.handlers.get("request", [])):
            handler(request)

        async def finish() -> None:
            await asyncio.sleep(self.delay_s)
            self.title_value = "after"
            for handler in list(self.handlers.get("requestfinished", [])):
                handler(request)

        self._task = asyncio.ensure_future(finish())


def _backend(page: _FakePage) -> WebGuiBackend:
    backend = WebGuiBackend.__new__(WebGuiBackend)
    backend._page = page  # type: ignore[assignment]
    return backend


@pytest.mark.anyio
async def test_press_key_returns_the_state_after_the_round_trip() -> None:
    page = _FakePage(round_trip=True)

    result = await _backend(page).press_key("F8")

    assert result.success
    assert result.page_title == "after"
    assert result.status_bar_message == "done"
    assert page.handlers["request"] == []  # listeners are removed again
    assert page.handlers["requestfinished"] == []
    assert page.handlers["requestfailed"] == []


@pytest.mark.anyio
async def test_press_key_without_a_round_trip_does_not_wait_for_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backend_module, "_KEY_ROUND_TRIP_START_S", 0.05)
    page = _FakePage(round_trip=False)

    result = await _backend(page).press_key("F1")

    assert result.success
    assert result.page_title == "before"


@pytest.mark.anyio
async def test_press_key_stops_waiting_for_a_round_trip_that_never_finishes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backend_module, "_KEY_ROUND_TRIP_FINISH_S", 0.05)
    page = _FakePage(round_trip=True, delay_s=5)

    result = await _backend(page).press_key("F8")

    assert result.success
    assert result.page_title == "before"
    page._task.cancel()  # type: ignore[attr-defined]


@pytest.mark.anyio
async def test_press_key_ignores_a_post_of_another_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    """A POST of an iframe or beacon is not the key's round trip and must not hold the key press."""
    monkeypatch.setattr(backend_module, "_KEY_ROUND_TRIP_START_S", 0.05)
    page = _FakePage(round_trip=True, delay_s=5, from_iframe=True)

    result = await _backend(page).press_key("F8")

    assert result.success
    assert result.page_title == "before"
    page._task.cancel()  # type: ignore[attr-defined]
