"""``extract_screen_info.js`` reads system, client, user, program and dynpro from the system information (#81)."""

import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

from sapwebguimcp.backend.webgui.js_helpers import load_js
from unittests.lang.node_runner import run_node

SNAPSHOT = Path(__file__).parent.parent / "testdata" / "html_snapshots" / "easy_access_de.html"
PREFIX = "sysInfoAreaMenuItemSAPITS_MBAR_"

RUN_JS = """
const { source, items, okCode, title } = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const fn = (0, eval)(source);
global.window = { location: { href: 'https://sap.example/webgui' } };
global.document = {
    title,
    getElementById: (id) => (id in items ? { getAttribute: (n) => (n === 'lsdata' ? items[id] : null) } : null),
    querySelector: (selector) => (selector.includes('ToolbarOkCode') && okCode ? { value: okCode } : null),
};
process.stdout.write(JSON.stringify(fn()));
"""
"""Runs the script against a fake document whose system information items hold the given ``lsdata`` strings."""


def _item(value: str) -> str:
    return json.dumps({"0": "abc", "1": "label", "3": True, "13": value})


def _run(items: dict[str, str], *, ok_code: str = "", title: str = "SAP Easy Access") -> dict[str, Any]:
    payload = {
        "source": load_js("extract_screen_info.js"),
        "items": {PREFIX + key: value for key, value in items.items()},
        "okCode": ok_code,
        "title": title,
    }
    result = run_node(RUN_JS, payload)
    assert isinstance(result, dict)
    return result


def test_reads_the_system_information_items() -> None:
    result = _run(
        {
            "SYSTEM": _item("ABC (100)"),
            "CLIENT": _item("100"),
            "USER": _item("TESTUSER"),
            "DYNPRO": _item("SAPLSMTR_NAVIGATION/0101"),
            "TRANSACTION": _item("SMEN"),
        }
    )
    assert result["systemName"] == "ABC"
    assert result["client"] == "100"
    assert result["user"] == "TESTUSER"
    assert result["program"] == "SAPLSMTR_NAVIGATION"
    assert result["dynpro"] == "0101"
    assert result["transaction"] == "SMEN"


def test_program_name_in_a_namespace_keeps_its_slashes() -> None:
    result = _run({"DYNPRO": _item("/ABC/SAPLEXAMPLE/0200")})
    assert result["program"] == "/ABC/SAPLEXAMPLE"
    assert result["dynpro"] == "0200"


def test_missing_items_give_empty_values_and_the_ok_code_is_the_transaction_fallback() -> None:
    result = _run({}, ok_code="/nSU3")
    assert result["systemName"] == ""
    assert result["client"] == ""
    assert result["user"] == ""
    assert result["transaction"] == "SU3"


def test_system_without_a_client_suffix_is_kept_as_is() -> None:
    assert _run({"SYSTEM": _item("ABC")})["systemName"] == "ABC"


class _SysInfoParser(HTMLParser):
    """Collects the ``lsdata`` of the system information menu items of a snapshot."""

    def __init__(self) -> None:
        super().__init__()
        self.items: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002
        attributes = dict(attrs)
        element_id = attributes.get("id") or ""
        if element_id.startswith(PREFIX) and attributes.get("lsdata"):
            self.items[element_id.removeprefix(PREFIX)] = attributes["lsdata"] or ""


def test_reads_a_real_web_gui_snapshot() -> None:
    parser = _SysInfoParser()
    parser.feed(SNAPSHOT.read_text(encoding="utf-8"))
    assert {"SYSTEM", "CLIENT", "USER", "DYNPRO", "TRANSACTION"} <= parser.items.keys()
    expected = {key: json.loads(value)["13"] for key, value in parser.items.items()}

    result = _run(parser.items)

    assert result["systemName"] == expected["SYSTEM"].rsplit(" (", 1)[0]
    assert result["client"] == expected["CLIENT"]
    assert result["user"] == expected["USER"]
    assert f"{result['program']}/{result['dynpro']}" == expected["DYNPRO"]
    assert result["transaction"] == expected["TRANSACTION"]


@pytest.mark.parametrize("key", ["SYSTEM", "CLIENT", "USER"])
def test_unparsable_lsdata_gives_an_empty_value(key: str) -> None:
    assert _run({key: "{not json"})[{"SYSTEM": "systemName", "CLIENT": "client", "USER": "user"}[key]] == ""
