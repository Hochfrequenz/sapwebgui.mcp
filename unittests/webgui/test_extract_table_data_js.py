"""``sap_read_table`` reports the grid's row count and whether rows of the range were not read (#100).

The Web GUI renders only part of a long ALV grid (the DOM held rows 1..90 of 300 right after execution) and only a
window of a table control, so the number of rows in the DOM is not the number of rows of the grid. The count the
Web GUI reports in the ``lsdata`` of the table is the grid's row count.
"""

# pylint: disable=protected-access

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock

import pytest

from sapwebguimcp.backend.webgui.backend import WebGuiBackend
from sapwebguimcp.backend.webgui.js_helpers import load_js
from unittests.lang.node_runner import run_node

SNAPSHOT = Path(__file__).parent.parent / "testdata" / "html_snapshots" / "se11_t000_content_de.html"

RUN_JS = """
const { source, params, elements, table, regularRows } = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const fn = (0, eval)(source);
const has = (id) => Object.prototype.hasOwnProperty.call(elements, id);
const wrap = (id) => {
    const e = elements[id];
    return {
        id,
        textContent: e.text,
        getAttribute: (name) => (name in e.attrs ? e.attrs[name] : null),
        querySelector: () => (e.input === null ? null : { value: e.input }),
    };
};
const tableElement = table && {
    id: table.id,
    getAttribute: (name) => (name === 'lsdata' ? table.lsdata : null),
    querySelectorAll: () => table.headers.map((text) => ({ textContent: text })),
};
const cell = (text) => ({
    textContent: text,
    querySelector: () => null,
});
const regularTable = regularRows && {
    querySelectorAll: (selector) => {
        if (selector.includes('th')) return [{ textContent: 'A' }, { textContent: 'B' }];
        return regularRows.map((texts) => ({ querySelectorAll: () => texts.map(cell) }));
    },
    querySelector: () => null,
};
global.document = {
    querySelector: (selector) => {
        if (selector === 'table[ct="STCS"]') return tableElement;
        return regularTable;
    },
    getElementById: (id) => (has(id) ? wrap(id) : null),
};
process.stdout.write(JSON.stringify(fn(params)));
"""
"""Runs the script against a fake document: ``elements`` maps ids to ``{attrs, text, input}``."""

COLUMNS = ("A", "B")


def _element(text: str, *, input_value: str | None = None, **attrs: str) -> dict[str, Any]:
    return {"attrs": attrs, "text": text, "input": input_value}


def _lsdata(total: dict[str, Any] | None) -> str | None:
    return None if total is None else json.dumps({"10": "MULTI", "34": total})


def _grid(
    rendered: int,
    *,
    lsdata: dict[str, Any] | None,
    blank_rows: int = 0,
    columns: tuple[str, ...] = COLUMNS,
) -> dict[str, Any]:
    """An ALV grid ``C1`` with ``rendered`` filled rows in the DOM, then ``blank_rows`` rendered rows without text."""
    elements: dict[str, Any] = {}
    for col, name in enumerate(columns):
        elements[f"grid#C1#0,{col}"] = _element(name)
    for row in range(1, rendered + blank_rows + 1):
        for col, name in enumerate(columns):
            text = f"{name}{row}" if row <= rendered else ""
            elements[f"grid#C1#{row},{col}"] = _element(text)
            elements[f"grid#C1#{row},{col}#if"] = _element(text)
    return {"id": "C1", "lsdata": _lsdata(lsdata), "headers": [], "elements": elements}


def _table_control(filled: int, rendered: int, *, row_count: int) -> dict[str, Any]:
    """An editable table control ``C1``: ``rendered`` rows in the DOM, the first ``filled`` with input values."""
    elements: dict[str, Any] = {}
    for row in range(1, rendered + 1):
        for col, name in enumerate(COLUMNS):
            value = f"{name}{row}" if row <= filled else ""
            elements[f"C1[{row},{col}]"] = _element("", input_value=value)
    lsdata = {"Type": "GuiTableControl", "rowCount": row_count}
    return {"id": "C1", "lsdata": _lsdata(lsdata), "headers": list(COLUMNS), "elements": elements}


def _run(
    grid: dict[str, Any], *, start_row: int = 1, end_row: int | None = None, max_rows: int = 500
) -> dict[str, Any]:
    payload = {
        "source": load_js("extract_table_data.js"),
        "params": {"startRow": start_row, "endRow": end_row, "maxRows": max_rows},
        "elements": grid["elements"],
        "table": {"id": grid["id"], "lsdata": grid["lsdata"], "headers": grid["headers"]},
    }
    return _run_payload(payload)


def _run_regular(rows: int, *, start_row: int = 1, end_row: int | None = None, max_rows: int = 500) -> dict[str, Any]:
    """A regular (non-ALV) table of ``rows`` filled rows: the document has no ``table[ct="STCS"]``."""
    payload = {
        "source": load_js("extract_table_data.js"),
        "params": {"startRow": start_row, "endRow": end_row, "maxRows": max_rows},
        "elements": {},
        "table": None,
        "regularRows": [[f"A{row}", f"B{row}"] for row in range(1, rows + 1)],
    }
    return _run_payload(payload)


def _run_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = run_node(RUN_JS, payload)
    assert isinstance(result, dict)
    return result


def test_long_grid_reports_its_total_and_truncation() -> None:
    result = _run(_grid(90, lsdata={"Type": "GuiGridView", "totalRows": 300}))

    assert result["totalRows"] == 300
    assert result.get("truncated") is True
    assert len(result["rows"]) == 90


def test_row_limit_on_long_grid_is_truncated() -> None:
    result = _run(_grid(90, lsdata={"Type": "GuiGridView", "totalRows": 300}), max_rows=10)

    assert len(result["rows"]) == 10
    assert result.get("truncated") is True
    assert result["totalRows"] == 300


def test_range_inside_rendered_rows_is_not_truncated() -> None:
    result = _run(_grid(90, lsdata={"Type": "GuiGridView", "totalRows": 300}), end_row=10)

    assert len(result["rows"]) == 10
    assert result.get("truncated") is False
    assert result["totalRows"] == 300


def test_whole_grid_rendered_is_not_truncated() -> None:
    """Regression guard: passes before the fix as well."""
    result = _run(_grid(5, lsdata={"Type": "GuiGridView", "totalRows": 5}))

    assert len(result["rows"]) == 5
    assert not result.get("truncated")
    assert result["totalRows"] == 5


def test_start_beyond_total_is_not_truncated() -> None:
    """No rows exist from row 20 on: none were left unread, and the count stays the grid's."""
    result = _run(_grid(5, lsdata={"Type": "GuiGridView", "totalRows": 5}), start_row=20)

    assert result["rows"] == []
    assert not result.get("truncated")
    assert result["totalRows"] == 5


def test_start_after_the_rendered_rows_of_a_long_grid_is_truncated() -> None:
    result = _run(_grid(90, lsdata={"Type": "GuiGridView", "totalRows": 300}), start_row=150)

    assert result["rows"] == []
    assert result.get("truncated") is True
    assert result["totalRows"] == 300


def test_stale_zero_total_does_not_shrink_the_count() -> None:
    result = _run(_grid(3, lsdata={"Type": "GuiGridView", "totalRows": 0}))

    assert result["totalRows"] == 3
    assert result.get("truncated") is False


def test_table_control_row_count_is_used() -> None:
    result = _run(_table_control(12, 12, row_count=28))

    assert len(result["rows"]) == 12
    assert result["totalRows"] == 28
    assert result.get("truncated") is True


def test_rendered_blank_rows_end_the_data() -> None:
    """Regression guard: blank input lines of an editable table control are not rows, its rowCount may count them."""
    result = _run(_table_control(3, 12, row_count=12))

    assert len(result["rows"]) == 3
    assert result["totalRows"] == 3
    assert not result.get("truncated")


def test_rendered_blank_rows_end_the_data_of_a_grid_too() -> None:
    result = _run(_grid(3, lsdata={"Type": "GuiGridView", "totalRows": 12}, blank_rows=9))

    assert len(result["rows"]) == 3
    assert result["totalRows"] == 3
    assert result.get("truncated") is False


def test_grid_without_count_keeps_old_behaviour() -> None:
    """Regression guard: without a count in the lsdata the rows read are the total and nothing is truncated."""
    result = _run(_grid(4, lsdata=None))

    assert len(result["rows"]) == 4
    assert result["totalRows"] == 4
    assert not result.get("truncated")


def test_unparsable_lsdata_is_ignored() -> None:
    grid = _grid(4, lsdata=None)
    grid["lsdata"] = "{not json"

    result = _run(grid)

    assert result["totalRows"] == 4
    assert result.get("truncated") is False


def test_row_count_below_the_rows_read_never_shrinks_the_total() -> None:
    result = _run(_grid(6, lsdata={"Type": "GuiGridView", "rowCount": 4}))

    assert result["totalRows"] == 6
    assert result.get("truncated") is False


def test_row_limit_equal_to_the_grid_total_is_not_truncated() -> None:
    """Regression guard (passes with the formula as it was): the limit reads the whole grid, nothing is left."""
    result = _run(_grid(20, lsdata={"Type": "GuiGridView", "totalRows": 20}), max_rows=20)

    assert len(result["rows"]) == 20
    assert result["totalRows"] == 20
    assert result.get("truncated") is False


def test_end_row_beyond_the_grid_total_is_not_truncated() -> None:
    """Regression guard (passes with the formula as it was): rows past the end of the grid do not exist."""
    result = _run(_grid(20, lsdata={"Type": "GuiGridView", "totalRows": 20}), end_row=50)

    assert len(result["rows"]) == 20
    assert result["totalRows"] == 20
    assert result.get("truncated") is False


def test_regular_table_with_end_row_inside_the_rows_is_not_truncated() -> None:
    """The requested range was read completely: rows after end_row are not part of it."""
    result = _run_regular(50, end_row=10)

    assert len(result["rows"]) == 10
    assert result["totalRows"] == 50
    assert result["truncated"] is False


def test_regular_table_cut_by_the_row_limit_is_truncated() -> None:
    result = _run_regular(50, max_rows=5)

    assert len(result["rows"]) == 5
    assert result["truncated"] is True


def test_regular_table_range_cut_by_the_row_limit_is_truncated() -> None:
    result = _run_regular(50, end_row=30, max_rows=5)

    assert len(result["rows"]) == 5
    assert result["truncated"] is True


def test_regular_table_read_completely_is_not_truncated() -> None:
    result = _run_regular(8)

    assert len(result["rows"]) == 8
    assert result["truncated"] is False


class _SnapshotParser(HTMLParser):
    """Collects the ids, attributes, texts and input values of the elements of one STCS table of a snapshot."""

    VOID: ClassVar[frozenset[str]] = frozenset(
        {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, Any]] = []
        self.table_id: str | None = None
        self.nodes: list[dict[str, Any]] = []
        self.headers: list[dict[str, Any]] = []
        self._table_node: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value or "" for name, value in attrs}
        node = {"tag": tag, "attrs": attributes, "text": [], "input": None}
        for open_node in self.stack:
            if tag in {"input", "textarea"} and open_node["input"] is None:
                open_node["input"] = attributes.get("value", "")
        self.nodes.append(node)
        if tag == "table" and attributes.get("ct") == "STCS" and self.table_id is None:
            self.table_id = attributes.get("id")
            self._table_node = node
        if self._table_node is not None and (tag == "th" or attributes.get("role") == "columnheader"):
            self.headers.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                node = self.stack[index]
                del self.stack[index:]
                if node is self._table_node:
                    self._table_node = None
                return

    def handle_data(self, data: str) -> None:
        for open_node in self.stack:
            open_node["text"].append(data)


def _snapshot_grid() -> dict[str, Any]:
    parser = _SnapshotParser()
    parser.feed(SNAPSHOT.read_text(encoding="utf-8"))
    assert parser.table_id is not None
    elements = {
        node["attrs"]["id"]: {"attrs": node["attrs"], "text": "".join(node["text"]), "input": node["input"]}
        for node in parser.nodes
        if node["attrs"].get("id", "").startswith(parser.table_id)
    }
    table = elements[parser.table_id]
    return {
        "id": parser.table_id,
        "lsdata": table["attrs"]["lsdata"],
        "headers": ["".join(header["text"]) for header in parser.headers],
        "elements": elements,
    }


def test_table_control_snapshot_reports_28_rows() -> None:
    result = _run(_snapshot_grid(), start_row=1, end_row=None, max_rows=100)

    assert result["totalRows"] == 28
    assert result.get("truncated") is True
    # The Web GUI renders rows 1..12 of the 28 rows of this table control
    assert [row["row"] for row in result["rows"]] == list(range(1, 13))


def _backend(evaluated: dict[str, Any]) -> WebGuiBackend:
    backend = WebGuiBackend.__new__(WebGuiBackend)
    page = MagicMock()
    page.evaluate = AsyncMock(return_value=evaluated)
    backend._page = page
    return backend


@pytest.mark.anyio
async def test_read_table_passes_truncated_through() -> None:
    backend = _backend(
        {
            "headers": ["A"],
            "rows": [{"row": 1, "data": {"A": "x"}}],
            "totalRows": 300,
            "startRow": 1,
            "endRow": 1,
            "truncated": True,
        }
    )

    result = await backend.read_table(start_row=1, max_rows=1)

    assert result.success
    assert result.truncated is True
    assert result.total_rows == 300


@pytest.mark.anyio
async def test_read_table_without_truncated_is_not_truncated() -> None:
    backend = _backend({"headers": ["A"], "rows": [], "totalRows": 0, "startRow": 1, "endRow": 1})

    result = await backend.read_table()

    assert result.truncated is False
