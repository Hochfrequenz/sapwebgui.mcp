"""``read_field_value.js`` returns the first non-empty value among the labelled fields (#42)."""

from typing import Any

import pytest

from sapwebguimcp.backend.webgui.js_helpers import load_js
from unittests.lang.node_runner import run_node

RUN_JS = """
const { source, labels, fields } = JSON.parse(require('fs').readFileSync(0, 'utf8'));
global.findInputByLabel = (label) => (label in fields ? fields[label] : null);
const fn = (0, eval)(source);
process.stdout.write(JSON.stringify(fn({ labels })));
"""
"""Runs the script with ``findInputByLabel`` stubbed to look the label up in ``fields``."""

AMBIGUOUS = {"ambiguous": True, "count": 2, "matches": []}
EMPTY = {"element": {"value": "  "}}
DATE = {"element": {"value": " 2026-10-07 "}}


def _run(labels: list[str], fields: dict[str, Any]) -> Any:
    return run_node(RUN_JS, {"source": load_js("read_field_value.js"), "labels": labels, "fields": fields})


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"B": DATE}, id="first label unknown"),
        pytest.param({"A": AMBIGUOUS, "B": DATE}, id="first label ambiguous"),
        pytest.param({"A": EMPTY, "B": DATE}, id="first value empty"),
        pytest.param({"A": {"element": {}}, "B": DATE}, id="first element has no value"),
    ],
)
def test_skips_labels_that_give_no_value(fields: dict[str, Any]) -> None:
    assert _run(["A", "B"], fields) == "2026-10-07"


def test_first_usable_label_wins() -> None:
    assert _run(["A", "B"], {"A": {"element": {"value": "07.10.2026"}}, "B": DATE}) == "07.10.2026"


def test_returns_null_when_no_label_gives_a_value() -> None:
    assert _run(["A", "B", "C"], {"A": EMPTY, "B": AMBIGUOUS}) is None


def test_returns_null_without_labels() -> None:
    assert _run([], {}) is None
