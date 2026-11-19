"""``to_playwright_key`` accepts the key names of every language pack (#14)."""

import pytest

from sapwebguimcp.backend.webgui.utils import is_sap_shortcut, to_playwright_key


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
    ],
)
def test_translation(given: str, expected: str) -> None:
    assert to_playwright_key(given) == expected


def test_localized_ctrl_is_still_a_status_bar_shortcut() -> None:
    assert is_sap_shortcut(to_playwright_key("Strg+S"))
