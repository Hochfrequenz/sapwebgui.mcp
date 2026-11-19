"""The status bar text is the message bar's own text, not the footer button labels (#79)."""

import pytest

from sapwebguimcp.backend.webgui.backend import _status_bar_arg
from sapwebguimcp.backend.webgui.js_helpers import load_js
from unittests.lang.node_runner import run_node

RUN_JS = """
const { source, arg, cases } = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const fn = (0, eval)(source);
const results = cases.map(({ message, iconClass, footer }) => {
    const text = { textContent: message };
    const bar = {
        className: 'lsMessageBar',
        parentElement: null,
        querySelector: (selector) => {
            if (selector === '.lsMessageBar__text') return text;
            return selector.toLowerCase().includes(iconClass.toLowerCase()) && iconClass ? {} : null;
        },
    };
    // the footer toolbar around the bar also holds the buttons; its text must never be read
    const footerArea = { className: '', parentElement: null, textContent: message + footer, querySelector: () => null };
    global.document = {
        querySelector: (selector) => {
            if (selector === '[id$="/sbar_msg"]') return bar;
            if (/msgarea/.test(selector)) return footerArea;
            return null;
        },
    };
    return fn(arg);
});
process.stdout.write(JSON.stringify(results));
"""
"""Runs the script once per case against a message bar inside a footer toolbar that also holds buttons."""

# (message, footer button labels, expected type)
CASES = [
    ("Bitte einen Tabellennamen eingeben", "Tabelleninhalt", "E"),
    ("Geschäftspartner 1234 wurde angelegt", "Enter", "S"),
    ("Wählen Sie die Rolle, in der Sie den Geschäftspartner anlegen wollen", "SichernEnterAbbrechen", "I"),
    ("Select the role in which you want to create the business partner", "SaveEnterCancel", "I"),
    ("Index", "Enter", "I"),
]


@pytest.fixture(scope="module")
def results() -> list[dict[str, str]]:
    cases = [{"message": m, "footer": f, "iconClass": "error" if t == "E" else ""} for m, f, t in CASES]
    payload = {"source": load_js("extract_status_bar.js"), "arg": _status_bar_arg(), "cases": cases}
    out: list[dict[str, str]] = run_node(RUN_JS, payload)
    return out


@pytest.mark.parametrize("index", range(len(CASES)))
def test_message_excludes_the_footer_buttons(results: list[dict[str, str]], index: int) -> None:
    assert results[index]["message"] == CASES[index][0]


def test_error_type_comes_from_the_icon(results: list[dict[str, str]]) -> None:
    assert results[0]["type"] == "E"


def test_a_bar_without_text_is_no_message_even_with_footer_buttons() -> None:
    cases = [{"message": "", "footer": "Enter", "iconClass": ""}]
    payload = {"source": load_js("extract_status_bar.js"), "arg": _status_bar_arg(), "cases": cases}
    assert run_node(RUN_JS, payload) == [{"type": "none", "message": ""}]


def test_success_type_comes_from_the_ok_icon() -> None:
    """The message bar marks a success with its "Ok" icon; the text alone has no success keyword."""
    cases = [{"message": "Index", "footer": "Enter", "iconClass": "__icon--Ok"}]
    payload = {"source": load_js("extract_status_bar.js"), "arg": _status_bar_arg(), "cases": cases}
    assert run_node(RUN_JS, payload)[0]["type"] == "S"
