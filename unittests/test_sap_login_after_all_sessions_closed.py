"""sap_login works again after every session was closed, also when Chrome's default context has no tab left (#104).

The recovery advice for an expired session is "log in again, then close the expired session". In CONNECT
mode, closing ``s1`` closes the only tab of Chrome's default context, and closing the further sessions closes
their own contexts. The next ``sap_login`` then takes the first-login path and must open a tab instead of
failing with "No browser tabs found".
"""

# pylint: disable=protected-access

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr
from sap_mcp_config import Config, SAPSystem

from sapwebguimcp.backend.manager import reset_backend_manager
from sapwebguimcp.backend.webgui.backend import WebGuiBackend
from sapwebguimcp.backend.webgui.browser import BrowserManager
from sapwebguimcp.models.config import BrowserMode
from sapwebguimcp.models.sap_results import LoginResult
from sapwebguimcp.tools.sap_login_impl import sap_login_impl

if TYPE_CHECKING:
    from collections.abc import Callable, Generator


class _Page:
    """A browser tab: closing it removes it from its context and fires the "close" listeners."""

    def __init__(self, context: _Context) -> None:
        self.context = context
        self._closed = False
        self._close_handlers: list[Callable[..., Any]] = []

    def on(self, event: str, handler: Callable[..., Any]) -> None:
        if event == "close":
            self._close_handlers.append(handler)

    def is_closed(self) -> bool:
        return self._closed

    async def close(self, **_: object) -> None:
        if self._closed:
            return
        self._closed = True
        self.context.pages.remove(self)
        for handler in list(self._close_handlers):
            handler(self)


class _Context:
    def __init__(self) -> None:
        self.pages: list[_Page] = []
        self.closed = False
        self._page_handlers: list[Callable[..., Any]] = []

    def on(self, event: str, handler: Callable[..., Any]) -> None:
        if event == "page":
            self._page_handlers.append(handler)

    async def new_page(self) -> _Page:
        if self.closed:
            raise RuntimeError("Target page, context or browser has been closed")
        page = _Page(self)
        self.pages.append(page)
        for handler in list(self._page_handlers):
            handler(page)
        return page

    async def close(self) -> None:
        self.closed = True
        for page in list(self.pages):
            await page.close()


class _Browser:
    def __init__(self, default_context: _Context) -> None:
        self.contexts = [default_context]

    async def new_context(self, **_: object) -> _Context:
        context = _Context()
        self.contexts.append(context)
        return context


def _config() -> Config:
    return Config(
        default_system="sysA",
        systems={
            "sysA": SAPSystem(
                connection_name="sysA",
                host="https://sap.example.com",
                client="100",
                user="testuser",
                password=SecretStr("testpass"),
                language="EN",
            )
        },
    )


@pytest.fixture(name="manager")
def _manager() -> Generator[BrowserManager, None, None]:
    """A CONNECT-mode browser manager on a Chrome whose default context has one tab."""
    settings = MagicMock()
    settings.browser_mode = BrowserMode.CONNECT
    settings.sap_url = ""
    default_context = _Context()
    manager = BrowserManager(settings)
    manager._browser = _Browser(default_context)  # type: ignore[assignment]
    manager._context = default_context  # type: ignore[assignment]
    manager._initialized = True

    async def fake_login(self: WebGuiBackend, **_: object) -> LoginResult:
        session_id = manager.registry.register(self._page)
        return LoginResult(success=True, session_id=session_id)

    reset_backend_manager()
    with (
        patch("sapwebguimcp.tools.sap_login_impl.get_settings", return_value=settings),
        patch("sapwebguimcp.tools.sap_login_impl.get_sap_config", return_value=_config()),
        patch("sapwebguimcp.tools.sap_login_impl.get_browser_manager", new=AsyncMock(return_value=manager)),
        patch("sapwebguimcp.backend.manager.get_browser_manager", new=AsyncMock(return_value=manager)),
        patch.object(WebGuiBackend, "login", new=fake_login),
        patch.object(WebGuiBackend, "start_keepalive", new=AsyncMock()),
        # A reconnect finds the same browser again: the default context still has no tab.
        patch.object(manager, "_reconnect", new=AsyncMock()),
    ):
        yield manager
    reset_backend_manager()


async def _close(manager: BrowserManager, session_id: str) -> None:
    """What sap_session_close does to the browser: close the session's tab (the registry drops it on close)."""
    await manager.registry.get_page(session_id).close()


@pytest.mark.anyio
async def test_login_again_after_closing_every_session(manager: BrowserManager) -> None:
    default_context = manager._context
    assert default_context is not None
    await default_context.new_page()  # the tab Chrome was started with

    first = await sap_login_impl()
    second = await sap_login_impl()
    assert (first.success, first.session_id) == (True, "s1")
    assert (second.success, second.session_id) == (True, "s2")

    await _close(manager, "s1")
    await _close(manager, "s2")
    assert not manager.registry.list_sessions()
    assert not default_context.pages

    third = await sap_login_impl()

    assert third.success, third.error
    assert third.session_id in manager.registry.list_sessions()
    page = manager.registry.get_page(third.session_id)
    # The first-login path logs in on a new tab of the default context, not in a login context.
    assert page.context is default_context
    assert not page.is_closed()


@pytest.mark.anyio
async def test_first_login_keeps_using_the_existing_tab(manager: BrowserManager) -> None:
    default_context = manager._context
    assert default_context is not None
    tab = await default_context.new_page()

    result = await sap_login_impl()

    assert result.success
    assert manager.registry.get_page("s1") is tab
    assert default_context.pages == [tab]
