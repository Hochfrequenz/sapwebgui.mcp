"""sap_login applies tls_skip_verify to a pre-launched Chrome and explains certificate errors (#80)."""

# pylint: disable=protected-access

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr
from sap_mcp_config import Config, SAPSystem

from sapwebguimcp.backend.webgui.backend import WebGuiBackend
from sapwebguimcp.backend.webgui.browser import BrowserManager
from sapwebguimcp.models.sap_results import LoginResult
from sapwebguimcp.tools.sap_login_impl import sap_login_impl


def _config(tls_skip_verify: bool) -> Config:
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
                tls_skip_verify=tls_skip_verify,
            )
        },
    )


@pytest.mark.anyio
@pytest.mark.usefixtures("empty_login_registry")
@pytest.mark.parametrize("flag", [True, False])
async def test_sap_login_passes_tls_skip_verify_to_the_backend(flag: bool) -> None:
    backend = AsyncMock()
    backend.login.return_value = LoginResult(success=True)
    settings = MagicMock()
    settings.sap_url = ""
    with (
        patch("sapwebguimcp.tools.sap_login_impl.get_settings", return_value=settings),
        patch("sapwebguimcp.tools.sap_login_impl.get_sap_config", return_value=_config(flag)),
        patch("sapwebguimcp.tools.sap_login_impl.get_backend", new=AsyncMock(return_value=backend)),
    ):
        await sap_login_impl()

    assert backend.login.call_args.kwargs["tls_skip_verify"] is flag


def _backend_failing_with(message: str) -> WebGuiBackend:
    backend = WebGuiBackend.__new__(WebGuiBackend)
    page = MagicMock()
    page.goto = AsyncMock(side_effect=RuntimeError(message))
    backend._page = page
    return backend


@pytest.mark.anyio
async def test_login_applies_the_ignore_to_the_browser_when_tls_skip_verify_is_set() -> None:
    manager = MagicMock()
    manager.ignore_certificate_errors = AsyncMock()
    backend = _backend_failing_with("boom")
    with patch("sapwebguimcp.backend.webgui.backend.get_browser_manager", new=AsyncMock(return_value=manager)):
        await backend.login("https://sap.example", "u", "p", "100", "EN", tls_skip_verify=True)
        manager.ignore_certificate_errors.assert_awaited_once()
        manager.ignore_certificate_errors.reset_mock()
        await backend.login("https://sap.example", "u", "p", "100", "EN")
        manager.ignore_certificate_errors.assert_not_awaited()


@pytest.mark.anyio
async def test_certificate_error_gets_guidance() -> None:
    backend = _backend_failing_with("Page.goto: net::ERR_CERT_AUTHORITY_INVALID at https://sap.example/")

    result = await backend.login("https://sap.example", "u", "p", "100", "EN")

    assert not result.success
    assert result.guidance is not None
    assert "tls_skip_verify" in result.guidance
    assert "--ignore-certificate-errors" in result.guidance


@pytest.mark.anyio
async def test_other_login_errors_get_no_certificate_guidance() -> None:
    backend = _backend_failing_with("Page.goto: net::ERR_NAME_NOT_RESOLVED at https://sap.example/")

    result = await backend.login("https://sap.example", "u", "p", "100", "EN")

    assert not result.success
    assert result.guidance is None


@pytest.mark.anyio
async def test_browser_manager_sets_ignore_certificate_errors_over_cdp_once() -> None:
    manager = BrowserManager()
    session = MagicMock()
    session.send = AsyncMock()
    browser = MagicMock()
    browser.new_browser_cdp_session = AsyncMock(return_value=session)
    manager._browser = browser

    await manager.ignore_certificate_errors()
    await manager.ignore_certificate_errors()

    session.send.assert_awaited_once_with("Security.setIgnoreCertificateErrors", {"ignore": True})
    browser.new_browser_cdp_session.assert_awaited_once()


@pytest.mark.anyio
async def test_browser_manager_survives_a_cdp_failure_and_retries_next_time() -> None:
    manager = BrowserManager()
    browser = MagicMock()
    browser.new_browser_cdp_session = AsyncMock(side_effect=RuntimeError("no CDP"))
    manager._browser = browser

    await manager.ignore_certificate_errors()
    await manager.ignore_certificate_errors()

    assert browser.new_browser_cdp_session.await_count == 2


@pytest.mark.anyio
async def test_browser_manager_without_a_browser_does_nothing() -> None:
    await BrowserManager().ignore_certificate_errors()
