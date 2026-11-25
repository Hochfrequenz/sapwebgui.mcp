"""The SE24 lookup tool reads the properties tab and the interface table of the class (#97)."""

# pylint: disable=protected-access

import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sapwebguimcp.lang.schema import LanguagePack
from sapwebguimcp.models import TableData, TableRow
from sapwebguimcp.models.se24_models import SE24Entry
from sapwebguimcp.tools import se24_tools

SNAPSHOTS_DIR = Path(__file__).parent / "testdata" / "se24_exploration"
TOOL_LOGGER = "sapwebguimcp.tools.se24_tools"


def _snapshot(name: str) -> str:
    return (SNAPSHOTS_DIR / f"{name}_de.yaml").read_text(encoding="utf-8")


def _table(name: str) -> TableData:
    return TableData.model_validate_json((SNAPSHOTS_DIR / f"{name}_de.json").read_text(encoding="utf-8"))


def _selected(label: str) -> str:
    return f'- tab "{label}" [selected]'


def _grid_snapshot(data_rows: int) -> str:
    """An interfaces tab snapshot whose grid shows ``data_rows`` data rows."""
    lines = [_selected("Interfaces"), "- grid:", '  - row "Interface Beschreibung":']
    lines += ['    - columnheader "Interface": Interface', '    - columnheader "Beschreibung": Beschreibung']
    for _ in range(data_rows):
        lines += [
            '  - row "Interface Beschreibung":',
            '    - gridcell "Interface":',
            '      - textbox "Interface"',
            '    - gridcell "Beschreibung":',
            '      - textbox "Beschreibung"',
        ]
    return "\n".join(lines)


class _FakeBackend:
    """A backend whose snapshot follows the tab that was clicked last, like SAP does."""

    def __init__(
        self,
        main: str,
        tabs: dict[str, str],
        table: TableData,
        failing_tabs: tuple[str, ...] = (),
    ) -> None:
        self._main = main
        self._tabs = tabs
        self._table = table
        self._failing_tabs = failing_tabs
        self._current: str | None = None
        self.events: list[str] = []
        self.wait_for_ready = AsyncMock()
        self.read_table = AsyncMock(side_effect=self._read_table)

    async def click_tab(self, label: str) -> None:
        # The class builder shows the English tab title "Interfaces"; the German variant of the pack does not exist
        if label in self._failing_tabs or label not in {"Eigenschaften", "Interfaces", "Methoden", "Attribute"}:
            raise ValueError(f"no tab {label}")
        self._current = label

    async def get_snapshot(self) -> str:
        if self._current is None:
            return self._main
        return self._tabs.get(self._current) or _selected(self._current)

    async def _read_table(self, *_args: object, **_kwargs: object) -> TableData:
        self.events.append(f"read_table after {self._current}")
        return self._table


def _tabs() -> dict[str, str]:
    return {
        "Eigenschaften": _snapshot("se24_cx_sy_zerodivide_properties"),
        "Interfaces": _snapshot("se24_cx_root_interfaces"),
    }


def _backend(tabs: dict[str, str] | None = None, failing_tabs: tuple[str, ...] = ()) -> _FakeBackend:
    return _FakeBackend(
        _snapshot("se24_cl_salv_table_main"),
        tabs or _tabs(),
        _table("se24_cx_root_interfaces_table"),
        failing_tabs=failing_tabs,
    )


async def _lookup(backend: _FakeBackend, lang_de: LanguagePack) -> SE24Entry:
    with patch.object(se24_tools, "fill_and_display", AsyncMock(return_value=None)):
        result = await se24_tools._lookup_class_on_initial_screen(
            backend,  # type: ignore[arg-type]
            "CX_SY_ZERODIVIDE",
            lang_de,
        )
    assert isinstance(result, SE24Entry), result
    return result


@pytest.mark.anyio
async def test_header_fields_and_interfaces_are_read(lang_de: LanguagePack) -> None:
    backend = _backend()
    entry = await _lookup(backend, lang_de)
    assert entry.superclass == "CX_SY_ARITHMETIC_ERROR"
    assert entry.is_final is True
    assert entry.description
    assert entry.package
    assert entry.interfaces == ["IF_MESSAGE", "IF_SERIALIZABLE_OBJECT"]
    backend.read_table.assert_awaited_once()
    assert backend.events == ["read_table after Interfaces"]


@pytest.mark.anyio
async def test_properties_tab_failure_keeps_the_entry(lang_de: LanguagePack, caplog: pytest.LogCaptureFixture) -> None:
    backend = _backend(failing_tabs=("Eigenschaften",))
    with caplog.at_level(logging.WARNING, logger=TOOL_LOGGER):
        entry = await _lookup(backend, lang_de)
    assert entry.superclass is None
    assert entry.description == ""
    assert entry.package == ""
    assert entry.interfaces == ["IF_MESSAGE", "IF_SERIALIZABLE_OBJECT"]
    assert any("properties" in r.getMessage().lower() for r in caplog.records if r.levelno == logging.WARNING)


@pytest.mark.anyio
async def test_warns_when_the_table_fills_the_visible_rows(
    lang_de: LanguagePack, caplog: pytest.LogCaptureFixture
) -> None:
    tabs = _tabs()
    tabs["Interfaces"] = _grid_snapshot(2)
    with caplog.at_level(logging.WARNING, logger=TOOL_LOGGER):
        entry = await _lookup(_backend(tabs), lang_de)
    assert entry.interfaces == ["IF_MESSAGE", "IF_SERIALIZABLE_OBJECT"]
    assert any("cut off" in r.getMessage() for r in caplog.records)


@pytest.mark.anyio
async def test_no_warning_when_the_grid_has_room(lang_de: LanguagePack, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=TOOL_LOGGER):
        await _lookup(_backend(), lang_de)
    assert not any("cut off" in r.getMessage() for r in caplog.records)


@pytest.mark.anyio
async def test_interfaces_tab_failure_skips_the_table_read(lang_de: LanguagePack) -> None:
    backend = _backend(failing_tabs=("Interfaces",))
    entry = await _lookup(backend, lang_de)
    assert entry.interfaces == []
    backend.read_table.assert_not_awaited()
    assert entry.superclass == "CX_SY_ARITHMETIC_ERROR"


@pytest.mark.anyio
async def test_table_read_failure_keeps_the_entry(lang_de: LanguagePack, caplog: pytest.LogCaptureFixture) -> None:
    backend = _backend()
    backend.read_table.side_effect = RuntimeError("grid vanished")
    with caplog.at_level(logging.WARNING, logger=TOOL_LOGGER):
        entry = await _lookup(backend, lang_de)
    assert entry.interfaces == []
    assert entry.superclass == "CX_SY_ARITHMETIC_ERROR"
    assert any(r.levelno == logging.WARNING for r in caplog.records)


@pytest.mark.anyio
async def test_failed_table_read_warns_and_keeps_the_entry(
    lang_de: LanguagePack, caplog: pytest.LogCaptureFixture
) -> None:
    backend = _backend()
    backend.read_table.side_effect = None
    backend.read_table.return_value = TableData.failure("boom")
    with caplog.at_level(logging.WARNING, logger=TOOL_LOGGER):
        entry = await _lookup(backend, lang_de)
    assert entry.interfaces == []
    assert entry.superclass == "CX_SY_ARITHMETIC_ERROR"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Could not read the interfaces table" in r.getMessage() for r in warnings)
    assert any(getattr(r, "object", None) == "CX_SY_ZERODIVIDE" for r in warnings)


@pytest.mark.anyio
async def test_methods_like_table_does_not_warn_about_cut_off(
    lang_de: LanguagePack, caplog: pytest.LogCaptureFixture
) -> None:
    tabs = _tabs()
    tabs["Interfaces"] = _grid_snapshot(2)
    methods_table = TableData(
        success=True,
        headers=["", "Methode"],
        rows=[TableRow(row=i, data={"": "", "Methode": f"METHOD_{i}"}) for i in range(1, 3)],
    )
    backend = _backend(tabs)
    backend.read_table.side_effect = None
    backend.read_table.return_value = methods_table
    with caplog.at_level(logging.WARNING, logger=TOOL_LOGGER):
        entry = await _lookup(backend, lang_de)
    assert entry.interfaces == []
    assert not any("cut off" in r.getMessage() for r in caplog.records)
