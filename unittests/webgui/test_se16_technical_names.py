"""Technical column names and row collection of the SE16N tool (#78)."""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from sapwebguimcp.backend.webgui.types import AriaSnapshot
from sapwebguimcp.lang.schema import LanguagePack
from sapwebguimcp.tools import se16_tools


def _backend(js_result: Any) -> AsyncMock:
    backend = AsyncMock()
    backend.evaluate_javascript.return_value = js_result
    return backend


@pytest.mark.anyio
async def test_technical_names_replace_the_titles() -> None:
    names = await se16_tools._read_technical_column_names(  # pylint: disable=protected-access
        _backend(["SPRAS", "LAISO"]), ["Sprache", "SprCode"]
    )
    assert names == ["SPRAS", "LAISO"]


@pytest.mark.anyio
@pytest.mark.parametrize("js_result", [["SPRAS"], ["SPRAS", "SPRAS"], None, "x"])
async def test_titles_are_kept_when_the_names_do_not_fit(js_result: Any) -> None:
    titles = ["Sprache", "SprCode"]
    assert await se16_tools._read_technical_column_names(_backend(js_result), titles) == titles  # pylint: disable=protected-access


@pytest.mark.anyio
async def test_titles_are_kept_when_the_script_fails() -> None:
    backend = AsyncMock()
    backend.evaluate_javascript.side_effect = RuntimeError("detached")
    titles = ["Sprache"]
    assert await se16_tools._read_technical_column_names(backend, titles) == titles  # pylint: disable=protected-access


@pytest.mark.anyio
async def test_rows_with_the_same_first_column_are_all_collected(lang_de: LanguagePack) -> None:
    """T002: the first column has the same value in every row, the grid fits on one page."""
    snapshot = (Path(__file__).parent / "testdata" / "se16_result_grids" / "t002_result_de.aria.txt").read_text(
        encoding="utf-8"
    )
    backend = AsyncMock()
    backend.get_snapshot.return_value = AriaSnapshot(snapshot)
    columns = ["SPRAS", "LASPEZ", "LAHQ", "LAISO", "SPTXT"]
    rows = await se16_tools._collect_rows_with_pagination(backend, 5, columns, lang_de)  # pylint: disable=protected-access
    assert [row["SPTXT"] for row in rows] == ["Chinesisch", "Koreanisch", "Rumänisch", "Serbisch", "Thailändisch"]
    backend.press_key.assert_not_called()
