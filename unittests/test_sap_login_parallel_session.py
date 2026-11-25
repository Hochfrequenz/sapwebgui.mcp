"""sap_login opens a new isolated tab when a session already exists instead of taking over the current one (#104)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr
from sap_mcp_config import Config, SAPSystem

from sapwebguimcp.models.sap_results import LoginResult
from sapwebguimcp.tools.sap_login_impl import sap_login_impl

_MODULE = "sapwebguimcp.tools.sap_login_impl"


def _make_sap_config(tls_skip_verify: bool = False) -> Config:
    return Config(
        default_system="sysA",
        systems={
            "sysA": SAPSystem(
                connection_name="sysA",
                host="https://sap.example.com",
                client="100",
                user="testuser",
                password=SecretStr("testpass"),
                language="DE",
                tls_skip_verify=tls_skip_verify,
            ),
        },
    )


def _make_manager(sessions: list[str]) -> MagicMock:
    manager = MagicMock()
    manager.registry.list_sessions = MagicMock(side_effect=lambda: list(sessions))
    manager.open_login_page = AsyncMock(return_value=MagicMock(name="login_page"))
    manager.close_login_page = AsyncMock()
    return manager


def _make_backend(login_result: LoginResult | None = None) -> AsyncMock:
    backend = AsyncMock()
    backend.login.return_value = login_result or LoginResult(success=True, session_id="s1")
    return backend


class _Patched:
    """Patches everything ``sap_login_impl`` reaches for and exposes the doubles."""

    def __init__(
        self,
        manager: MagicMock,
        current_backend: AsyncMock,
        new_backend: AsyncMock | None = None,
        tls_skip_verify: bool = False,
    ) -> None:
        self.manager = manager
        self.current_backend = current_backend
        self.new_backend = new_backend or _make_backend(LoginResult(success=True, session_id="s2"))
        self.session_backend = _make_backend()
        settings = MagicMock()
        settings.sap_url = ""

        async def get_backend(session: str | None = None, tool_name: str = "") -> AsyncMock:
            del tool_name
            return self.session_backend if session is not None else self.current_backend

        self.get_backend = AsyncMock(side_effect=get_backend)
        self.web_gui_backend = MagicMock(return_value=self.new_backend)
        self._patches = [
            patch(f"{_MODULE}.get_settings", return_value=settings),
            patch(f"{_MODULE}.get_sap_config", return_value=_make_sap_config(tls_skip_verify)),
            patch(f"{_MODULE}.get_backend", new=self.get_backend),
            patch(f"{_MODULE}.get_browser_manager", new=AsyncMock(return_value=manager)),
            patch(f"{_MODULE}.WebGuiBackend", new=self.web_gui_backend),
        ]

    def __enter__(self) -> "_Patched":
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc: object) -> None:
        for p in reversed(self._patches):
            p.stop()


@pytest.mark.anyio
async def test_first_login_uses_the_current_tab() -> None:
    manager = _make_manager([])
    current = _make_backend()
    with _Patched(manager, current) as p:
        result = await sap_login_impl()

    assert result.success
    manager.open_login_page.assert_not_awaited()
    p.get_backend.assert_awaited_once_with(tool_name="sap_login")
    current.login.assert_awaited_once()
    current.start_keepalive.assert_awaited_once()


@pytest.mark.anyio
async def test_login_with_an_existing_session_opens_a_new_one() -> None:
    manager = _make_manager(["s1"])
    current = _make_backend()
    with _Patched(manager, current) as p:
        result = await sap_login_impl()

    assert result.success
    assert result.session_id == "s2"
    page = manager.open_login_page.return_value
    manager.open_login_page.assert_awaited_once_with(ignore_https_errors=False)
    p.web_gui_backend.assert_called_once_with(page)
    p.new_backend.login.assert_awaited_once()
    current.login.assert_not_awaited()
    manager.close_login_page.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("tls_skip_verify", [False, True])
async def test_parallel_login_checks_certificates_unless_the_system_skips_tls_verification(
    tls_skip_verify: bool,
) -> None:
    manager = _make_manager(["s1"])
    with _Patched(manager, _make_backend(), tls_skip_verify=tls_skip_verify):
        await sap_login_impl()

    manager.open_login_page.assert_awaited_once_with(ignore_https_errors=tls_skip_verify)


@pytest.mark.anyio
async def test_parallel_login_starts_keepalive_on_the_new_session() -> None:
    manager = _make_manager(["s1"])
    with _Patched(manager, _make_backend()) as p:
        await sap_login_impl()

    p.get_backend.assert_awaited_once_with(session="s2", tool_name="sap_login")
    p.session_backend.start_keepalive.assert_awaited_once()
    p.new_backend.start_keepalive.assert_not_awaited()


@pytest.mark.anyio
async def test_failed_parallel_login_closes_its_tab() -> None:
    manager = _make_manager(["s1"])
    failing = _make_backend(LoginResult.failure("bad"))
    with _Patched(manager, _make_backend(), failing) as p:
        result = await sap_login_impl()

    assert not result.success
    manager.close_login_page.assert_awaited_once_with(manager.open_login_page.return_value)
    p.session_backend.start_keepalive.assert_not_awaited()
    failing.start_keepalive.assert_not_awaited()


@pytest.mark.anyio
async def test_parallel_login_exception_closes_its_tab() -> None:
    manager = _make_manager(["s1"])
    failing = _make_backend()
    failing.login.side_effect = RuntimeError("boom")
    with _Patched(manager, _make_backend(), failing), pytest.raises(RuntimeError, match="boom"):
        await sap_login_impl()

    manager.close_login_page.assert_awaited_once_with(manager.open_login_page.return_value)


@pytest.mark.anyio
async def test_open_login_page_failure_propagates() -> None:
    manager = _make_manager(["s1"])
    manager.open_login_page.side_effect = RuntimeError("no tab")
    current = _make_backend()
    with _Patched(manager, current) as p, pytest.raises(RuntimeError, match="no tab"):
        await sap_login_impl()

    current.login.assert_not_awaited()
    p.new_backend.login.assert_not_awaited()
    manager.close_login_page.assert_not_awaited()


@pytest.mark.anyio
async def test_concurrent_first_logins_do_not_share_the_tab() -> None:
    sessions: list[str] = []
    manager = _make_manager(sessions)
    current = _make_backend()

    async def slow_login(**_: object) -> LoginResult:
        await asyncio.sleep(0)
        sessions.append("s1")
        return LoginResult(success=True, session_id="s1")

    current.login.side_effect = slow_login
    with _Patched(manager, current):
        await asyncio.gather(sap_login_impl(), sap_login_impl())

    assert current.login.await_count == 1
    assert manager.open_login_page.await_count == 1
