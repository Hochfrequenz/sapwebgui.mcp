"""Offline guard for the automatic ``integration`` marker (#1022).

Live SAP tests are identified by the fixtures they request. If a fixture is
renamed, the hook in ``unittests/conftest.py`` would silently become inert, so
these tests pin the rules and the fixture names.
"""

import ast
from pathlib import Path

import pytest

# Imported from conftest on purpose: the hook and predicate live there and must stay importable.
from unittests.conftest import is_live_sap_item, pytest_collection_modifyitems

_UNITTESTS = Path(__file__).parent
_WEBGUI = _UNITTESTS / "webgui"


@pytest.mark.parametrize(
    ("fixtures", "path", "expected"),
    [
        (["sap_mcp_client"], _WEBGUI / "test_x.py", True),
        (["sap_mcp_client"], _UNITTESTS / "test_x.py", True),
        (["backend"], _UNITTESTS / "test_x.py", False),
        (["backend"], _WEBGUI / "test_x.py", False),
        (["tmp_path", "monkeypatch"], _WEBGUI / "test_x.py", False),
        ([], _WEBGUI / "test_x.py", False),
    ],
)
def test_is_live_sap_item(fixtures, path, expected):
    assert is_live_sap_item(fixtures, path) is expected


def test_hook_marks_only_live_items():
    class FakeItem:
        def __init__(self, fixturenames, path):
            self.fixturenames = fixturenames
            self.path = path
            self.markers = []

        def add_marker(self, marker):
            self.markers.append(marker.name)

    live = FakeItem(["sap_mcp_client"], _WEBGUI / "test_a.py")
    offline = FakeItem(["tmp_path"], _WEBGUI / "test_b.py")
    pytest_collection_modifyitems([live, offline])
    assert live.markers == ["integration"]
    assert offline.markers == []


def _defined_fixtures(conftest: Path) -> set[str]:
    tree = ast.parse(conftest.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                if "fixture" in ast.unparse(target):
                    names.add(node.name)
    return names


def test_live_fixtures_still_exist():
    assert "sap_mcp_client" in _defined_fixtures(_WEBGUI / "conftest.py")


def test_marker_is_registered(pytestconfig):
    markers = pytestconfig.getini("markers")
    assert any(m.startswith("integration:") for m in markers)
