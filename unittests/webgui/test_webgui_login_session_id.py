"""sap_login returns the session ID, sap_get_screen_info and sap_session_list fill the system details (#81)."""

# pylint: disable=protected-access

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sapwebguimcp.backend.webgui.backend import WebGuiBackend
from sapwebguimcp.backend.webgui.models.session_registry import SessionRegistry

DETAILS = {
    "transaction": "SU3",
    "title": "Maintain User Profile",
    "url": "https://sap.example/webgui",
    "program": "SAPLSUU5",
    "dynpro": "0100",
    "systemName": "ABC",
    "client": "100",
    "user": "TESTUSER",
}


def _make_backend(evaluate_result: Any = None) -> WebGuiBackend:
    backend = WebGuiBackend.__new__(WebGuiBackend)
    page = MagicMock()
    page.is_closed.return_value = False
    page.evaluate = AsyncMock(return_value=evaluate_result)
    page.title = AsyncMock(return_value="Maintain User Profile")
    backend._page = page
    return backend


def _login_ready_backend() -> WebGuiBackend:
    backend = _make_backend()
    backend._page.goto = AsyncMock()
    backend._page.wait_for_load_state = AsyncMock()
    backend._find_okcode_field = AsyncMock(return_value=object())  # type: ignore[method-assign]
    return backend


@pytest.mark.anyio
async def test_login_returns_the_registry_session_id() -> None:
    registry = SessionRegistry()
    backend = _login_ready_backend()
    with (
        patch.object(type(backend), "_get_registry", new=AsyncMock(return_value=registry)),
        patch.object(type(backend), "_capture_sap_identity", new=AsyncMock()),
        patch.object(type(backend), "_read_page_language", new=AsyncMock(return_value=None)),
    ):
        result = await backend.login("https://sap.example/webgui", "user", "secret", "100", "EN")

    assert result.success
    assert result.session_id == "s1"
    assert registry.session_id_of(backend._page) == "s1"


@pytest.mark.anyio
async def test_login_on_an_already_registered_page_returns_its_existing_session_id() -> None:
    registry = SessionRegistry()
    backend = _login_ready_backend()
    registry.register(MagicMock())  # s1 belongs to another tab
    registry.register(backend._page)  # s2
    with (
        patch.object(type(backend), "_get_registry", new=AsyncMock(return_value=registry)),
        patch.object(type(backend), "_capture_sap_identity", new=AsyncMock()),
        patch.object(type(backend), "_read_page_language", new=AsyncMock(return_value=None)),
    ):
        result = await backend.login("https://sap.example/webgui", "user", "secret", "100", "EN")

    assert result.session_id == "s2"


@pytest.mark.anyio
async def test_get_screen_info_fills_the_system_details() -> None:
    backend = _make_backend(DETAILS)

    info = await backend.get_screen_info()

    assert info.success
    assert (info.transaction, info.program, info.dynpro) == ("SU3", "SAPLSUU5", "0100")
    assert (info.system_name, info.client, info.user) == ("ABC", "100", "TESTUSER")


@pytest.mark.anyio
async def test_get_screen_info_maps_empty_values_to_none() -> None:
    backend = _make_backend({"title": "t", "url": "u", "transaction": "", "systemName": "", "client": "", "user": ""})

    info = await backend.get_screen_info()

    assert info.transaction is None
    assert info.system_name is None
    assert info.client is None
    assert info.user is None


@pytest.mark.anyio
async def test_list_sessions_fills_the_system_details() -> None:
    backend = _make_backend()
    registry = SessionRegistry()
    page = MagicMock()
    page.is_closed.return_value = False
    page.title = AsyncMock(return_value="Maintain User Profile")
    page.evaluate = AsyncMock(return_value=DETAILS)
    registry.register(page)
    with patch.object(type(backend), "_get_registry", new=AsyncMock(return_value=registry)):
        sessions = await backend.list_sessions()

    assert len(sessions) == 1
    assert sessions[0].session_id == "s1"
    assert (sessions[0].tcode, sessions[0].system_name, sessions[0].client, sessions[0].user) == (
        "SU3",
        "ABC",
        "100",
        "TESTUSER",
    )


@pytest.mark.anyio
async def test_list_sessions_survives_unreadable_details() -> None:
    backend = _make_backend()
    registry = SessionRegistry()
    page = MagicMock()
    page.is_closed.return_value = False
    page.title = AsyncMock(return_value="t")
    page.evaluate = AsyncMock(side_effect=RuntimeError("page gone"))
    registry.register(page)
    with patch.object(type(backend), "_get_registry", new=AsyncMock(return_value=registry)):
        sessions = await backend.list_sessions()

    assert [s.session_id for s in sessions] == ["s1"]
    assert sessions[0].system_name is None
