"""Tests for browser manager singleton initialization."""

import asyncio
import logging
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import sapwebguimcp.backend.webgui.browser as browser_module
from sapwebguimcp.models.config import BrowserMode, SapGuiSettings


def test_get_browser_manager_init_lock_is_per_event_loop() -> None:
    """The singleton init lock must be recreated when the event loop changes."""

    async def get_lock() -> asyncio.Lock:
        return browser_module._get_browser_manager_init_lock()

    original_lock = browser_module._browser_manager_init_lock
    original_lock_loop = browser_module._browser_manager_init_lock_loop
    try:
        with asyncio.Runner() as first_runner:
            first_lock = first_runner.run(get_lock())
        with asyncio.Runner() as second_runner:
            second_lock = second_runner.run(get_lock())

        assert first_lock is not second_lock
    finally:
        browser_module._browser_manager_init_lock = original_lock
        browser_module._browser_manager_init_lock_loop = original_lock_loop


@pytest.mark.anyio
async def test_get_browser_manager_waits_for_initialization(monkeypatch) -> None:
    """Concurrent callers must wait for the singleton to finish initializing."""
    original_manager = browser_module._browser_manager
    browser_module._browser_manager = None
    initialize_started = asyncio.Event()
    allow_initialize_to_finish = asyncio.Event()
    initialize_calls = 0

    async def fake_initialize(self) -> None:
        nonlocal initialize_calls
        initialize_calls += 1
        initialize_started.set()
        await allow_initialize_to_finish.wait()
        self._initialized = True

    monkeypatch.setattr(browser_module.BrowserManager, "initialize", fake_initialize)

    try:
        first_task = asyncio.create_task(browser_module.get_browser_manager())
        await initialize_started.wait()

        second_task = asyncio.create_task(browser_module.get_browser_manager())
        await asyncio.sleep(0)
        assert not second_task.done(), "second caller should wait for initialization to finish"

        allow_initialize_to_finish.set()
        first_manager, second_manager = await asyncio.gather(first_task, second_task)

        assert initialize_calls == 1
        assert first_manager is second_manager
        assert second_manager.is_initialized is True
    finally:
        browser_module._browser_manager = original_manager


class _FakePage:
    """Stands in for a Playwright page of a login context."""

    def __init__(self, context: "_FakeContext") -> None:
        self.context = context
        self.registrations: list[tuple[str, Callable[..., Any]]] = []
        self.close = AsyncMock()
        self._closed = False

    def on(self, event: str, handler: Callable[..., Any]) -> None:
        self.registrations.append((event, handler))

    def is_closed(self) -> bool:
        return self._closed

    def close_handlers(self) -> list[Callable[..., Any]]:
        return [handler for event, handler in self.registrations if event == "close"]

    def mark_closed_and_fire(self) -> None:
        """Playwright removes the page from context.pages before it emits "close"."""
        self._closed = True
        for handler in self.close_handlers():
            handler(self)


class _FakeContext:
    """Stands in for a Playwright browser context that records listeners and pages."""

    def __init__(self) -> None:
        self.pages: list[_FakePage] = []
        self.registrations: list[tuple[str, Callable[..., Any]]] = []
        self.close = AsyncMock()
        self.new_page_error: BaseException | None = None

    def on(self, event: str, handler: Callable[..., Any]) -> None:
        self.registrations.append((event, handler))

    def emit_page(self) -> _FakePage:
        page = _FakePage(self)
        self.pages.append(page)
        for event, handler in list(self.registrations):
            if event == "page":
                handler(page)
        return page

    async def new_page(self) -> _FakePage:
        if self.new_page_error is not None:
            raise self.new_page_error
        return self.emit_page()


def _manager_with_context() -> tuple[browser_module.BrowserManager, MagicMock, _FakeContext]:
    context = _FakeContext()
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    manager = browser_module.BrowserManager()
    manager._initialized = True
    manager._browser = browser
    return manager, browser, context


async def _drain_tasks(manager: browser_module.BrowserManager) -> None:
    """Let the tasks scheduled from sync Playwright listeners finish."""
    await asyncio.sleep(0)
    pending = list(manager._login_context_close_tasks)
    if pending:
        await asyncio.gather(*pending)


@pytest.mark.anyio
@pytest.mark.parametrize("ignore_https_errors", [False, True])
async def test_open_login_page_creates_an_isolated_context(ignore_https_errors: bool) -> None:
    manager, browser, context = _manager_with_context()

    page = await manager.open_login_page(ignore_https_errors=ignore_https_errors)

    browser.new_context.assert_awaited_once_with(
        viewport={"width": 1280, "height": 800}, ignore_https_errors=ignore_https_errors
    )
    assert page is context.pages[0]
    assert context in manager._login_contexts


@pytest.mark.anyio
async def test_login_page_gets_only_one_close_listener() -> None:
    manager, _, context = _manager_with_context()

    page = await manager.open_login_page(ignore_https_errors=False)

    assert isinstance(page, _FakePage)
    assert len(page.close_handlers()) == 1
    page.mark_closed_and_fire()
    await _drain_tasks(manager)
    context.close.assert_awaited_once()


@pytest.mark.anyio
async def test_login_context_closes_only_after_its_last_page() -> None:
    manager, _, context = _manager_with_context()
    first = await manager.open_login_page(ignore_https_errors=False)
    second = context.emit_page()
    assert isinstance(first, _FakePage)

    first.mark_closed_and_fire()
    await _drain_tasks(manager)
    context.close.assert_not_awaited()
    assert context in manager._login_contexts

    second.mark_closed_and_fire()
    await _drain_tasks(manager)
    context.close.assert_awaited_once()
    assert context not in manager._login_contexts


@pytest.mark.anyio
async def test_open_login_page_closes_the_context_when_the_tab_cannot_open() -> None:
    manager, _, context = _manager_with_context()
    context.new_page_error = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await manager.open_login_page(ignore_https_errors=False)

    context.close.assert_awaited_once()
    assert not manager._login_contexts


@pytest.mark.anyio
async def test_open_login_page_closes_the_context_when_cancelled_while_opening_the_tab() -> None:
    manager, _, context = _manager_with_context()
    cancelled = asyncio.CancelledError()
    context.new_page_error = cancelled

    with pytest.raises(asyncio.CancelledError) as excinfo:
        await manager.open_login_page(ignore_https_errors=False)

    assert excinfo.value is cancelled
    context.close.assert_awaited_once()
    assert not manager._login_contexts


@pytest.mark.anyio
async def test_open_login_page_without_browser_raises() -> None:
    manager, _, _ = _manager_with_context()
    manager._browser = None

    with pytest.raises(RuntimeError, match="Browser not connected"):
        await manager.open_login_page(ignore_https_errors=False)


@pytest.mark.anyio
async def test_reconnect_clears_login_contexts(monkeypatch: pytest.MonkeyPatch) -> None:
    manager, _, _ = _manager_with_context()
    await manager.open_login_page(ignore_https_errors=False)
    assert manager._login_contexts
    monkeypatch.setattr(browser_module.BrowserManager, "initialize", AsyncMock())

    await manager._reconnect()

    assert not manager._login_contexts
    assert not manager._login_pages_with_listener


@pytest.mark.anyio
async def test_failing_context_close_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    manager, _, context = _manager_with_context()
    context.close.side_effect = RuntimeError("close failed")
    page = await manager.open_login_page(ignore_https_errors=False)
    assert isinstance(page, _FakePage)

    with caplog.at_level(logging.WARNING, logger=browser_module.__name__):
        page.mark_closed_and_fire()
        await _drain_tasks(manager)

    context.close.assert_awaited_once()
    assert not manager._login_contexts
    assert any(
        record.levelno == logging.WARNING and "Could not close login browser context" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.anyio
async def test_close_login_page_falls_back_to_closing_the_context() -> None:
    manager, _, context = _manager_with_context()
    page = await manager.open_login_page(ignore_https_errors=False)
    assert isinstance(page, _FakePage)
    page.close.side_effect = RuntimeError("tab is gone")

    await manager.close_login_page(page)  # type: ignore[arg-type]

    context.close.assert_awaited_once()
    assert not manager._login_contexts


@pytest.mark.anyio
async def test_close_closes_login_contexts() -> None:
    manager, _, context = _manager_with_context()
    manager._settings = SapGuiSettings(_env_file=None, browser_mode=BrowserMode.CONNECT)  # type: ignore[call-arg]
    manager._playwright = None
    await manager.open_login_page(ignore_https_errors=False)

    await manager.close()

    context.close.assert_awaited_once()
    assert not manager._login_contexts
