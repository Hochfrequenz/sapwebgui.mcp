"""Backend manager — singleton entry point for tools."""

from __future__ import annotations

import logging

from sapwebguimcp.backend.webgui.backend import WebGuiBackend
from sapwebguimcp.backend.webgui.browser import close_browser_manager, get_browser_manager
from sapwebguimcp.session_language import set_session_language

logger = logging.getLogger(__name__)


class BackendManager:  # pylint: disable=too-few-public-methods
    """Manages WebGUI backend instances across sessions."""

    def __init__(self) -> None:
        self.backend_type = "webgui"
        self._backends: dict[str, WebGuiBackend] = {}  # Cache by session ID
        self._page_ids: dict[str, int] = {}  # Track page identity for cache invalidation

    async def get_or_create(
        self,
        session: str | None = None,
        agent_id: str | None = None,
        tool_name: str = "",
    ) -> WebGuiBackend:
        """Get or create the WebGUI backend instance for the given session.

        Caches WebGuiBackend instances by session ID. Returns cached instance
        if the underlying page is still the same, creates a new one otherwise.
        """
        browser_manager = await get_browser_manager()
        page = await browser_manager.get_or_create_session_page_checked(session, agent_id, tool_name)
        session_key = session or browser_manager.registry.primary_session
        # Same registry WebGuiBackend._get_registry() records the language in.
        set_session_language(browser_manager.registry.language_of(session_key))
        cached = self._backends.get(session_key)
        if cached is not None and self._page_ids.get(session_key) == id(page):
            return cached
        backend = WebGuiBackend(page)
        self._backends[session_key] = backend
        self._page_ids[session_key] = id(page)
        return backend

    async def close(self) -> None:
        """Shut down the browser and release resources."""
        await close_browser_manager()
        self._backends.clear()
        self._page_ids.clear()


# -- Singleton --

_backend_manager: BackendManager | None = None  # pylint: disable=invalid-name


def get_backend_manager() -> BackendManager:
    """Get the global BackendManager singleton (lazy init)."""
    global _backend_manager  # noqa: PLW0603  # pylint: disable=global-statement
    if _backend_manager is None:
        _backend_manager = BackendManager()
    return _backend_manager


async def get_backend(
    session: str | None = None,
    agent_id: str | None = None,
    tool_name: str = "",
) -> WebGuiBackend:
    """Convenience: get a backend instance for the given session.

    This is the primary entry point for all tools.
    """
    manager = get_backend_manager()
    return await manager.get_or_create(session, agent_id, tool_name)


async def get_webgui_backend(
    session: str | None = None,
    agent_id: str | None = None,
    tool_name: str = "",
) -> WebGuiBackend:
    """Get a WebGuiBackend instance. Asserts backend_type is webgui."""
    backend = await get_backend(session, agent_id, tool_name)
    assert isinstance(backend, WebGuiBackend)
    return backend


async def close_backend() -> None:
    """Shut down the active backend (called during server shutdown)."""
    if _backend_manager is not None:
        await _backend_manager.close()


def reset_backend_manager() -> None:
    """Reset the singleton (for testing)."""
    global _backend_manager  # noqa: PLW0603  # pylint: disable=global-statement
    _backend_manager = None
