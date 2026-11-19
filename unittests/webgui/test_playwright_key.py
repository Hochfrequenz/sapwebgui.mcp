"""``to_playwright_key`` accepts the key names of every language pack (#14)."""

from unittest.mock import AsyncMock, patch

import pytest

from sapwebguimcp.backend.webgui.utils import is_sap_shortcut, to_playwright_key
from sapwebguimcp.server import mcp


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("Ctrl+S", "Control+S"),
        ("ctrl+s", "Control+s"),
        ("Strg+S", "Control+S"),
        ("Control+S", "Control+S"),
        ("Ctrl+Shift+F1", "Control+Shift+F1"),
        ("Strg+Umschalt+F1", "Control+Shift+F1"),
        ("Ctrl+Alt+Delete", "Control+Alt+Delete"),
        ("Eingabe", "Enter"),
        ("Enter", "Enter"),
        ("F8", "F8"),
        ("Shift+F3", "Shift+F3"),
        ("PageDown", "PageDown"),
        ("Ctrl++", "Control++"),
        ("+", "+"),
        ("Ctrl + S", "Control+S"),
        ("Strg + Umschalt + F1", "Control+Shift+F1"),
        ("Ctrl + PageDown", "Control+PageDown"),
    ],
)
def test_translation(given: str, expected: str) -> None:
    assert to_playwright_key(given) == expected


def test_localized_ctrl_is_still_a_status_bar_shortcut() -> None:
    assert is_sap_shortcut(to_playwright_key("Strg+S"))


@pytest.mark.anyio
async def test_browser_keyboard_translates_the_key() -> None:
    tool = await mcp.get_tool("browser_keyboard")
    backend = AsyncMock()
    backend._page.keyboard.press = AsyncMock()  # pylint: disable=protected-access
    with patch("sapwebguimcp.tools.browser_tools.get_backend", new=AsyncMock(return_value=backend)):
        result = await tool.fn(key="Strg+S")
    backend._page.keyboard.press.assert_awaited_once_with("Control+S")  # pylint: disable=protected-access
    assert result.key == "Strg+S"
