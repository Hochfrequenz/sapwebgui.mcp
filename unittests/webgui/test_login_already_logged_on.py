"""A parallel sap_login must not end the user's other logons on SAP's "already logged on" page (#104).

SAP's multiple-logon page offers to continue *and end* the other logons, or to continue *without*
ending them. A further login of the same user selects the option that keeps the other logons and
checks that it is selected before it clicks "Continue"; if it cannot, it does not continue at all.

Nobody has captured that page yet, so the HTML below is hand-written from SAP's standard option
texts, not a snapshot.
"""

# pylint: disable=protected-access

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import async_playwright

from sapwebguimcp.backend.webgui.backend import WebGuiBackend


def _page_html(options: list[tuple[str, str, bool]], *, wrap_in_label: bool = False) -> str:
    """An "already logged on" page with radio buttons ``(id, label, checked)`` and a Continue button."""
    rows = []
    for option_id, label, checked in options:
        radio = f'<input type="radio" name="multi" id="{option_id}"{" checked" if checked else ""}>'
        if wrap_in_label:
            rows.append(f"<div><label>{radio} {label}</label></div>")
        else:
            rows.append(f'<div>{radio}<label for="{option_id}">{label}</label></div>')
    return (
        "<html><body><form>"
        "<p>User TESTUSER is already logged on in client 100</p>" + "".join(rows) + '<button type="button" '
        "onclick=\"document.body.dataset.continued = 'yes'\">Continue</button>"
        "</form></body></html>"
    )


_EN_OPTIONS = [
    ("end", "Continue with this logon and end any other logons in system", True),
    ("keep", "Continue with this logon, without ending any other logons in system", False),
    ("stop", "Terminate this logon", False),
]
_DE_OPTIONS = [
    ("end", "Mit dieser Anmeldung fortfahren und alle anderen Anmeldungen im System beenden", True),
    ("keep", "Mit dieser Anmeldung fortfahren, ohne die anderen Anmeldungen im System zu beenden", False),
    ("stop", "Diese Anmeldung abbrechen", False),
]
_IT_OPTIONS = [
    ("end", "Continuare con questo logon e terminare tutti gli altri logon nel sistema", True),
    ("keep", "Continuare con questo logon senza terminare gli altri logon nel sistema", False),
    ("stop", "Interrompere questo logon", False),
]


async def _on_html(html: str, action: Any) -> Any:
    """Load ``html`` into headless Chromium (no network) and run ``action`` on a backend for that page."""
    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE"))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            reason = f"Chromium cannot be launched here: {str(exc).splitlines()[0]}"
            if os.environ.get("CI"):
                pytest.fail(reason)  # CI installs Chromium; a silent skip would leave the JS untested
            pytest.skip(reason)
        try:
            context = await browser.new_context()
            await context.route("**/*", lambda route: route.abort())
            page = await context.new_page()
            await page.set_content(html, wait_until="domcontentloaded")
            return await action(WebGuiBackend(page))
        finally:
            await browser.close()


async def _select_and_read(backend: WebGuiBackend) -> tuple[bool, list[str]]:
    selected = await backend._select_keep_other_logons()
    checked = await backend._page.evaluate(
        "() => Array.from(document.querySelectorAll('input[type=radio]')).filter((r) => r.checked).map((r) => r.id)"
    )
    return selected, checked


@pytest.mark.anyio
@pytest.mark.parametrize("options", [_EN_OPTIONS, _DE_OPTIONS, _IT_OPTIONS], ids=["EN", "DE", "IT"])
@pytest.mark.parametrize("wrap_in_label", [False, True], ids=["label-for", "wrapping-label"])
async def test_the_option_that_keeps_the_other_logons_is_selected(
    options: list[tuple[str, str, bool]], wrap_in_label: bool
) -> None:
    selected, checked = await _on_html(_page_html(options, wrap_in_label=wrap_in_label), _select_and_read)

    assert selected is True
    assert checked == ["keep"]


@pytest.mark.anyio
async def test_a_label_in_the_text_after_the_radio_button_is_found() -> None:
    html = (
        "<html><body><p>User TESTUSER is already logged on</p>"
        '<input type="radio" name="multi" id="end" checked> Continue with this logon and end any other logons<br>'
        '<input type="radio" name="multi" id="keep"> Continue with this logon, without ending any other logons<br>'
        "</body></html>"
    )
    selected, checked = await _on_html(html, _select_and_read)

    assert selected is True
    assert checked == ["keep"]


@pytest.mark.anyio
async def test_no_option_found_when_the_page_offers_only_ending_the_other_logons() -> None:
    html = _page_html([_EN_OPTIONS[0], _EN_OPTIONS[2]])
    selected, checked = await _on_html(html, _select_and_read)

    assert selected is False
    assert checked == ["end"]


@pytest.mark.anyio
async def test_no_option_found_on_a_page_without_radio_buttons() -> None:
    html = "<html><body><p>User TESTUSER is already logged on</p><button>Continue</button></body></html>"
    selected, _checked = await _on_html(html, _select_and_read)

    assert selected is False


@pytest.mark.anyio
async def test_two_matching_options_are_not_guessed_between() -> None:
    html = _page_html([("a", _EN_OPTIONS[1][1], False), ("b", _EN_OPTIONS[1][1] + " (all clients)", False)])
    selected, checked = await _on_html(html, _select_and_read)

    assert selected is False
    assert not checked


@pytest.mark.anyio
async def test_a_disabled_option_is_not_reported_as_selected() -> None:
    html = _page_html(_EN_OPTIONS).replace('id="keep"', 'id="keep" disabled')
    selected, checked = await _on_html(html, _select_and_read)

    assert selected is False
    assert checked == ["end"]


# ---------------------------------------------------------------------------
# login(): the "already logged on" branch, with a mocked page like the other login tests
# ---------------------------------------------------------------------------

_CONTINUE_MARK = 'button:has-text("Continue")'


def _backend_on_already_logged_on_page() -> tuple[WebGuiBackend, list[str]]:
    """A backend whose page shows SAP's "already logged on" page after the logon button is clicked."""
    clicks: list[str] = []
    page = MagicMock()
    page.goto = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.query_selector = AsyncMock(return_value=object())
    page.fill = AsyncMock()
    page.evaluate = AsyncMock()
    page.content = AsyncMock(return_value="<p>User TESTUSER is already logged on in client 100</p>")

    async def click(selector: str, **_: object) -> None:
        clicks.append(selector)

    async def wait_for_selector(selector: str, **_: object) -> None:
        if selector == "#ToolbarOkCode" and not any(_CONTINUE_MARK in c for c in clicks):
            raise TimeoutError("no OK-code field")

    page.click = AsyncMock(side_effect=click)
    page.wait_for_selector = AsyncMock(side_effect=wait_for_selector)
    backend = WebGuiBackend.__new__(WebGuiBackend)
    backend._page = page
    return backend, clicks


async def _login(backend: WebGuiBackend, *, selected: bool, keep_other_logons: bool) -> tuple[Any, AsyncMock]:
    select = AsyncMock(return_value=selected)
    with (
        patch.object(WebGuiBackend, "_find_okcode_field", new=AsyncMock(return_value=None)),
        patch.object(WebGuiBackend, "_post_login_setup", new=AsyncMock(return_value="s2")),
        patch.object(WebGuiBackend, "_select_keep_other_logons", new=select),
    ):
        result = await backend.login(
            "https://sap.example", "testuser", "p", "100", "EN", keep_other_logons=keep_other_logons
        )
    return result, select


@pytest.mark.anyio
async def test_parallel_login_continues_after_selecting_the_option_that_keeps_the_other_logons() -> None:
    backend, clicks = _backend_on_already_logged_on_page()

    result, select = await _login(backend, selected=True, keep_other_logons=True)

    assert result.success
    assert result.session_id == "s2"
    select.assert_awaited_once()
    assert clicks[0] == "#LOGON_BUTTON"
    assert any(_CONTINUE_MARK in c for c in clicks[1:])


@pytest.mark.anyio
async def test_parallel_login_does_not_continue_when_the_option_is_missing() -> None:
    backend, clicks = _backend_on_already_logged_on_page()

    result, select = await _login(backend, selected=False, keep_other_logons=True)

    assert not result.success
    select.assert_awaited_once()
    assert clicks == ["#LOGON_BUTTON"]
    assert "already logged on" in (result.error or "")
    assert "other session" in (result.error or "")


@pytest.mark.anyio
async def test_first_login_still_clicks_continue_without_choosing_an_option() -> None:
    """The first login's handling of the page predates #104 and stays as it was."""
    backend, clicks = _backend_on_already_logged_on_page()

    result, select = await _login(backend, selected=False, keep_other_logons=False)

    assert result.success
    select.assert_not_awaited()
    assert any(_CONTINUE_MARK in c for c in clicks[1:])
