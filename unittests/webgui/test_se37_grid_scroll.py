"""The SE37 tool scrolls a parameter grid that shows only part of its rows (#76)."""

# pylint: disable=protected-access

from unittest.mock import AsyncMock

import pytest

from sapwebguimcp.lang.schema import LanguagePack
from sapwebguimcp.tools import se37_tools


def _grid(*names: str) -> str:
    return "\n".join(f'- gridcell "{name}"' for name in names)


@pytest.mark.anyio
async def test_scrolls_until_the_grid_does_not_change(lang_de: LanguagePack) -> None:
    pages = [_grid("A", "B"), _grid("B", "C"), _grid("C", "D"), _grid("C", "D") + "\n- cell E2E 5 ms"]
    backend = AsyncMock()
    backend.get_snapshot.side_effect = pages
    result = await se37_tools._capture_tab_snapshot(backend, lang_de.se37.import_tab)
    assert result is not None
    assert result.count('gridcell "') == 6  # A B, B C, C D
    assert backend.press_key.await_count == 3


@pytest.mark.anyio
async def test_no_scrolling_when_not_wanted(lang_de: LanguagePack) -> None:
    backend = AsyncMock()
    backend.get_snapshot.return_value = _grid("A")
    await se37_tools._capture_tab_snapshot(backend, lang_de.se37.properties_tab, scroll=False)
    backend.press_key.assert_not_called()


@pytest.mark.anyio
async def test_missing_tab_gives_none(lang_de: LanguagePack) -> None:
    backend = AsyncMock()
    backend.click_tab.side_effect = ValueError("no tab")
    assert await se37_tools._capture_tab_snapshot(backend, lang_de.se37.import_tab) is None
