"""``sap_read_table`` and ``TableData`` tell the caller how to read the rows that were not read (#100).

Live evidence: after PageDown in an ALV grid the Web GUI adds the further rows to the DOM with absolute row ids, so
reading again with ``start_row`` after the previous ``end_row`` returns them. A table control holds only its window.
"""

from __future__ import annotations

import pytest
from fastmcp import FastMCP

from sapwebguimcp.models import TableData
from sapwebguimcp.tools.sap_tools import register_sap_tools


def test_truncated_description_says_how_to_read_the_next_rows() -> None:
    description = TableData.model_fields["truncated"].description or ""

    assert "PageDown" in description
    assert "start_row" in description
    assert "end_row" in description
    assert "table control" in description


def test_total_rows_description_says_it_is_the_reported_count() -> None:
    description = TableData.model_fields["total_rows"].description or ""

    assert "reports" in description
    assert "rows returned" in description


@pytest.mark.anyio
async def test_read_table_tool_description_and_docstring_name_the_fields_and_the_paging() -> None:
    mcp = FastMCP("test")
    register_sap_tools(mcp)
    tool = await mcp.get_tool("sap_read_table")

    for text in (tool.description or "", tool.fn.__doc__ or ""):
        assert "truncated" in text
        assert "total_rows" in text
        assert "PageDown" in text
        assert "start_row" in text
