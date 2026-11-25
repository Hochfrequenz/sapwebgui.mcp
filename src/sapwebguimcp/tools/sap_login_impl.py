"""Standalone implementation for sap_login, extracted for testability."""

import asyncio
from typing import Optional

from sapwebguimcp.backend.manager import get_backend
from sapwebguimcp.backend.webgui.backend import WebGuiBackend
from sapwebguimcp.backend.webgui.browser import get_browser_manager
from sapwebguimcp.models import LoginResult
from sapwebguimcp.models.config import get_sap_config, get_settings

__all__ = ["sap_login_impl"]

# WebGUI ICF service path appended to a system's host to form the login URL.
_WEBGUI_PATH = "/sap/bc/gui/sap/its/webgui"


# Serialises the "is there a session already?" check together with the login that follows it, so two concurrent
# first logins cannot both pick the current tab. One lock per event loop, like the browser manager's init lock.
_login_lock: asyncio.Lock | None = None
_login_lock_loop: asyncio.AbstractEventLoop | None = None


def _get_login_lock() -> asyncio.Lock:
    """Get the login lock for the running event loop."""
    global _login_lock, _login_lock_loop  # noqa: PLW0603  # pylint: disable=global-statement
    current_loop = asyncio.get_running_loop()
    if _login_lock is None or _login_lock_loop is not current_loop:
        _login_lock = asyncio.Lock()
        _login_lock_loop = current_loop
    return _login_lock


def _webgui_url_from_host(host: str) -> str:
    """Return the WebGUI login URL for *host*, or ``""`` if *host* is empty."""
    return f"{host}{_WEBGUI_PATH}" if host else ""


async def sap_login_impl(
    url: Optional[str] = None,
    client: Optional[str] = None,
    system_key: Optional[str] = None,
    session_id: Optional[str] = None,
) -> LoginResult:
    """
    Log into SAP.

    Args:
        url: SAP Web GUI URL (WebGUI only). If not provided, derives from the
            selected system's ``host`` in systems.json, falling back to ``SAP_URL``.
        client: SAP client/mandant (3-digit string). If not provided, uses shared config.
        system_key: Dictionary key from systems.json (e.g. "dev-100"). Overrides default_system.
        session_id: Session ID for multi-session support.

    Returns:
        LoginResult indicating login success or what action is needed.
    """
    settings = get_settings()
    sap_cfg = get_sap_config()

    effective_key = system_key or sap_cfg.default_system
    system = sap_cfg.systems.get(effective_key)
    if system is None:
        if system_key is not None:
            return LoginResult.failure(
                f"System key {system_key!r} not found in systems.json. "
                f"Available system keys: {list(sap_cfg.systems.keys())}"
            )
        system = sap_cfg.get_default()

    user, password = system.user, system.password.get_secret_value()
    effective_client = client or system.client
    # systems.json is the source of truth: when the chosen system has a host
    # configured we use it. ``settings.sap_url`` (legacy ``SAP_URL`` env var)
    # is only a fallback for systems with no ``host`` set, otherwise it would
    # silently override a non-default ``system_key`` and route the user to the
    # default system instead (issue #659).
    effective_url = url or _webgui_url_from_host(system.host) or settings.sap_url
    language = system.language

    if not effective_url:
        return LoginResult.failure(
            "No SAP URL provided. Either pass a URL parameter or set SAP_URL, "
            "or configure 'host' in ~/.config/sap-mcp/systems.json."
        )

    if not all([user, password, effective_client]):
        return LoginResult.failure(
            "Credentials not configured. Check user/password/client in ~/.config/sap-mcp/systems.json."
        )

    browser_manager = await get_browser_manager()
    async with _get_login_lock():

        async def login_on(target: WebGuiBackend) -> LoginResult:
            return await target.login(
                url=effective_url or "",
                username=user,
                password=password,
                client=effective_client,
                language=language,
                session_id=session_id,
                connection_name=system.connection_name,
                tls_skip_verify=bool(system.tls_skip_verify),
            )

        if not browser_manager.registry.list_sessions():
            # First login: use the tab the browser already has.
            backend = await get_backend(tool_name="sap_login")
            result = await login_on(backend)
            if result.success:
                # Never start keepalive for attached (user-owned) sessions unless the user asks (issue #1009).
                await backend.start_keepalive()
            return result

        # A session exists already: log in on a new, isolated tab so it is not taken over (issue #104).
        page = await browser_manager.open_login_page()
        succeeded = False
        try:
            result = await login_on(WebGuiBackend(page))
            if result.success:
                backend = await get_backend(session=result.session_id, tool_name="sap_login")
                await backend.start_keepalive()
                succeeded = True
            return result
        finally:
            if not succeeded:
                await browser_manager.close_login_page(page)
