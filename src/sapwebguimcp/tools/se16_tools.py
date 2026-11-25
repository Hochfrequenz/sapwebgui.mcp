# pylint: disable=too-many-lines
"""
SE16 (Data Browser) query tool for SAP table data.

This module provides a tool to query SAP table data via SE16N transaction,
returning structured row data with automatic pagination for large result sets.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from sapwebguimcp import lang
from sapwebguimcp.backend.manager import get_backend
from sapwebguimcp.backend.webgui.js_helpers import script_arg
from sapwebguimcp.backend.webgui.parsers.se16_parser import parse_se16_columns, parse_se16_hit_count, parse_se16_rows
from sapwebguimcp.backend.webgui.types import AriaSnapshot
from sapwebguimcp.models import SE16FileSummary, SE16Result, SE16Row
from sapwebguimcp.tools.se11_tools import _lookup_object_on_initial_screen
from sapwebguimcp.utils import resolve_output_file_path, write_json_output_file

if TYPE_CHECKING:
    from sapwebguimcp.backend.webgui.backend import WebGuiBackend
    from sapwebguimcp.lang.schema import LanguagePack


logger = logging.getLogger(__name__)

__all__ = ["register_se16_tools"]


# =============================================================================
# Constants
# =============================================================================

# Default maximum rows to return
DEFAULT_MAX_HITS = 100


# Wait time between pages
PAGE_WAIT_TIME = timedelta(seconds=1)

# Maximum pages to traverse (supports SE16N's 9999 row limit at ~13 rows/page)
MAX_PAGES = 800


# =============================================================================
# SE11 Field Order Helper
# =============================================================================


async def _get_field_order_from_se11(backend: WebGuiBackend, table: str, t: LanguagePack) -> dict[str, int] | None:
    """
    Get field order from SE11 for a table.

    Returns a dict mapping field name (uppercase) to 0-based row index,
    or None if SE11 lookup fails.

    The order in SE11 matches the row order in SE16N's selection criteria grid.
    """
    try:
        # Navigate to SE11 with clean state
        await backend.enter_transaction("/n")
        await backend.wait_for_ready()
        tx_result = await backend.enter_transaction("SE11")
        if not tx_result.success:
            return None
        await backend.wait_for_ready()

        result = await _lookup_object_on_initial_screen(backend, table, "table", t)

        # Press F3 (Back) to exit SE11 and return to clean state
        # This prevents state issues when navigating to SE16N next
        await backend.press_key("F3")
        await backend.wait_for_ready()

        # Check if we got an SE11Entry (success) vs SE11Error
        if hasattr(result, "fields") and result.fields:
            # Build mapping: field_name -> row_index
            field_order: dict[str, int] = {}
            for idx, field in enumerate(result.fields):
                field_order[field.name.upper()] = idx
            logger.info("Got field order from SE11", extra={"table": table, "fields": len(field_order)})
            return field_order

        logger.warning("SE11 lookup returned no fields", extra={"table": table})
        return None

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("SE11 lookup failed", extra={"table": table, "error": str(e)})
        return None


# =============================================================================
# SE16 Query Implementation
# =============================================================================


def _empty_failure(
    error: str,
    table: str,
    retrieved_at: datetime,
    total_hits: int = 0,
    columns: list[str] | None = None,
    filter_warnings: list[str] | None = None,
) -> SE16Result:
    """Create a failure SE16Result with empty rows."""
    return SE16Result.failure(
        error=error,
        table=table,
        total_hits=total_hits,
        returned_rows=0,
        truncated=False,
        columns=columns or [],
        rows=[],
        filter_warnings=filter_warnings or [],
        retrieved_at=retrieved_at,
    )


async def _fill_se16n_table_name(backend: WebGuiBackend, table: str, t: LanguagePack) -> str | None:
    """
    Fill SE16N table name field.

    Tries the label of every language of the merged view, then the main form input.

    Returns: Error message if failed, None if successful.
    """
    for label in t.se16.table_label:
        try:
            await backend.fill_field(label, table.upper())
            return None
        except ValueError:  # pylint: disable=broad-exception-caught
            pass

    # Fallback: fill main form input, skipping toolbar/combobox inputs.
    if await backend.fill_main_input(table.upper(), list(t.se16.table_label)):
        return None

    return "Failed to set the table name field. Field not found by its label."


async def _type_table_name_with_validation(backend: WebGuiBackend, table: str, t: LanguagePack) -> str | None:
    """
    Type table name in SE16N and trigger validation with Enter.

    This approach mimics user behavior to trigger SAP's table validation
    round-trip, which populates the selection criteria grid.

    Returns:
        Error message if failed, None if successful.
    """
    for textbox_name in t.se16.table_label:
        try:
            if await backend.focus_and_type(textbox_name, table.upper(), delay_ms=50):
                logger.info("Typed table name", extra={"table": table, "field": textbox_name})
                logger.info("Pressing Enter to trigger table validation")
                await backend.press_key("Enter")
                return None
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Typing in table field", extra={"field": textbox_name, "error": str(e)})

    # Fallback to fill_field approach
    if fill_error := await _fill_se16n_table_name(backend, table, t):
        return fill_error
    logger.warning("Used fallback fill_field for table name")
    await backend.press_key("Enter")
    return None


# The grid has rows once one of them holds text other than the placeholder of an empty row ("Empty Empty ...").
# The placeholder is a pack text: ``texts.empty.source`` is its regex source (spec section 8). In this Python
# string ``\\\\s`` reaches JS as ``\\s`` (a JS string escape), and the regex engine sees ``\s``.
_GRID_HAS_ROWS_JS = """
(params) => {
    const empty = new RegExp('^(?:(?:' + params.texts.empty.source + ')\\\\s*)+$', params.texts.empty.flags);
    for (const grid of document.querySelectorAll('[role="grid"]')) {
        for (const row of grid.querySelectorAll('[role="row"]')) {
            if (row.querySelector('[role="columnheader"]')) continue;
            const text = row.textContent?.trim() || '';
            if (text && !empty.test(text)) return true;
        }
    }
    return false;
}
"""


async def _wait_for_grid_rows(backend: WebGuiBackend, t: LanguagePack, timeout_seconds: int = 5) -> bool:
    """
    Wait for SE16N selection criteria grid to populate with data rows.

    Returns:
        True if grid has rows, False if timeout.
    """
    for i in range(timeout_seconds * 2):  # Poll every 500ms
        result = await backend.evaluate_javascript(_GRID_HAS_ROWS_JS, script_arg({"empty": t.se16.empty_cell}))
        if result:
            logger.info("Table structure loaded", extra={"poll_iteration": i})
            return True
        await backend.wait(500)

    logger.warning("Grid not populated after polling", extra={"timeout_seconds": timeout_seconds})
    return False


async def _fill_se16n_max_hits(backend: WebGuiBackend, max_hits: int, t: LanguagePack) -> None:
    """
    Fill SE16N max hits field.

    Tries the label of every language of the merged view. Ignores errors since
    the field has a default value.
    """
    for label in t.se16.max_hits_label:
        try:
            await backend.fill_field(label, str(max_hits))
            return
        except ValueError:  # pylint: disable=broad-exception-caught
            pass


async def _fill_filter_by_locator(
    backend: WebGuiBackend, element_id: str | None, selector: str | None, value: str, field_name: str
) -> bool:
    """
    Fill a filter field using element-targeted input via protocol methods.

    Tries element ID first, then selector. Uses fill_element_by_locator()
    which clicks, clears, types slowly, and Tabs to blur.

    Returns:
        True if fill succeeded, False otherwise.
    """
    # Try by element ID first (use attribute selector for IDs with special chars)
    if element_id:
        try:
            if await backend.fill_element_by_locator(f'[id="{element_id}"]', value):
                logger.info("Filled filter via locator (id)", extra={"field": field_name, "value": value})
                return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Fill by ID failed", extra={"error": str(e)})

    # Try by CSS selector
    if selector:
        try:
            if await backend.fill_element_by_locator(selector, value):
                logger.info("Filled filter via locator (selector)", extra={"field": field_name, "value": value})
                return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Fill by selector failed", extra={"error": str(e)})

    return False


def _check_table_not_found(snapshot: str, table: str, t: LanguagePack) -> str | None:
    """
    Check if snapshot indicates table not found error.

    Scans the whole snapshot, so it uses the narrow ``se16.table_not_found`` fragment, not the wider
    ``common.does_not_exist`` (a result row could contain "nicht vorhanden").

    Returns:
        Error message if table not found, None if table exists.
    """
    if t.se16.table_not_found.contains(snapshot):
        return f"Table '{table}' not found in SAP"  # lang-ok: our own message

    # No explicit error - will check columns after parsing
    return None


def _check_no_entries_found(snapshot: str, t: LanguagePack) -> bool:
    """Check if snapshot contains 'no values found' message (empty but existing table)."""
    return t.se16.no_values_found.contains(snapshot)


def _check_selection_screen_columns(columns: list[str], t: LanguagePack) -> bool:
    """
    Check if parsed columns indicate we're still on the selection screen.

    The selection screen grid has headers that a result grid does not (field name, from-value, to-value,
    technical name). Two of them mean the selection screen.

    Returns:
        True if columns indicate selection screen, False otherwise.
    """
    return sum(1 for column in set(columns) if t.se16.selection_columns.equals(column)) >= 2


# Technical field names of the result grid columns. The column header cells carry the name in the SID of their
# lsdata (``wnd[0]/shellcont/shell/colSPRAS``); the selection column has the SID ``.../shell/col`` without a name.
_TECHNICAL_COLUMN_NAMES_JS = r"""() => {
  const found = [];
  for (const th of document.querySelectorAll('[role="grid"] th[role="columnheader"]')) {
    const match = /"SID":"[^"]*\/shell\/col([^"]+)"/.exec(th.getAttribute('lsdata') || '');
    if (match) { found.push([parseInt(th.getAttribute('lsmatrixcolindex') || '0', 10), match[1]]); }
  }
  found.sort((a, b) => a[0] - b[0]);
  return found.map((entry) => entry[1]);
}"""


async def _read_technical_column_names(backend: WebGuiBackend, titles: list[str]) -> list[str]:
    """Return the technical field names of the result columns, or ``titles`` when they cannot be read (#78).

    The ARIA tree only knows the column titles, which are not unique ("Name 1", "Verantw. Stelle" ...) and differ
    from the field names the desktop server returns. The names are only used when there is exactly one per title.
    """
    try:
        names = await backend.evaluate_javascript(_TECHNICAL_COLUMN_NAMES_JS)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("Could not read the technical column names", extra={"error": str(e)})
        return titles
    if isinstance(names, list) and len(names) == len(titles) and len(set(names)) == len(names):
        return [str(name) for name in names]
    logger.warning(
        "Technical column names do not match the column titles, keeping the titles",
        extra={"names": len(names) if isinstance(names, list) else None, "titles": len(titles)},
    )
    return titles


async def _focus_grid(backend: WebGuiBackend) -> None:
    """Focus the ALV grid for pagination (required for PageDown to work)."""
    try:
        await backend.click_element("[role='grid']")
        await backend.wait(500)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("Could not focus grid", extra={"error": str(e)})


def _row_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """Identity of a result row for duplicate detection: all its cell values (no separator collisions)."""
    return tuple(row.values())


async def _collect_rows_with_pagination(  # pylint: disable=too-many-locals,too-many-arguments,too-many-positional-arguments
    backend: WebGuiBackend,
    total_hits: int,
    columns: list[str],
    t: LanguagePack,
    ctx: Context | None = None,
) -> list[dict[str, Any]]:
    """
    Collect all rows from SE16N results using pagination.

    Uses PageDown to scroll through lazy-loaded ALV grid, collecting
    rows from each page until all are collected or no new rows found.

    Args:
        backend: WebGuiBackend instance
        total_hits: Expected total rows (from "Number of Hits")
        columns: Column names for row parsing
        t: Language pack of the session
        ctx: FastMCP context for progress reporting (optional)

    Returns:
        List of row dicts
    """
    all_rows: list[dict[str, Any]] = []
    seen_keys: set[tuple[Any, ...]] = set()  # Track unique row keys to detect duplicates
    page_num = 0
    stuck_count = 0
    last_first_key: tuple[Any, ...] | None = None

    while len(all_rows) < total_hits and page_num < MAX_PAGES:
        # Get snapshot and parse rows
        snapshot = AriaSnapshot(await backend.get_snapshot())
        rows = parse_se16_rows(snapshot, t, columns)

        if not rows:
            logger.debug("No rows found on page", extra={"page": page_num})
            stuck_count += 1
            if stuck_count >= 3:
                logger.warning("No rows found for 3 consecutive pages, stopping")
                break
            await backend.wait(int(PAGE_WAIT_TIME.total_seconds() * 2000))
            continue

        stuck_count = 0

        # A row is identified by all its cells: the first column alone is not unique (the key column of
        # a table may repeat, e.g. T002 or a language-dependent text table) and dropped all but one row (#78)
        first_key = _row_key(rows[0])

        # Detect if we're stuck on the same page
        if first_key == last_first_key:
            logger.debug("Same first row, likely at end", extra={"page": page_num})
            break

        last_first_key = first_key

        # Add new rows (skip rows already collected from a previous page)
        new_count = 0
        for row in rows:
            row_key = _row_key(row)
            if row_key not in seen_keys:
                seen_keys.add(row_key)
                all_rows.append(row)
                new_count += 1

        logger.debug(
            "Collected rows from page",
            extra={
                "page": page_num,
                "new_rows": new_count,
                "total_rows": len(all_rows),
                "total_hits": total_hits,
            },
        )

        # Report progress if context available
        if ctx:
            try:
                await ctx.report_progress(progress=len(all_rows), total=total_hits)
            except Exception:  # pylint: disable=broad-exception-caught
                pass  # Progress reporting is optional, don't fail on errors

        # Check if we've collected all rows
        if len(all_rows) >= total_hits:
            logger.info("Collected all rows", extra={"count": len(all_rows)})
            break

        # PageDown to next page
        await backend.press_key("PageDown")
        await backend.wait(int(PAGE_WAIT_TIME.total_seconds() * 1000))
        page_num += 1

    return all_rows


# Maximum number of offered SE16N selection fields named in a filter failure message
_SE16N_MAX_OFFERED_FIELDS = 50

# Upper bound for the pages the Web GUI selection grid is scrolled through (SE11 allows 749 fields;
# 120 pages cover them at 7 visible rows per page)
_SE16N_MAX_SELECTION_PAGES = 120


@dataclass
class _FilterFillResult:
    """Outcome of filling the SE16N selection criteria grid on the desktop backend."""

    unapplied_fields: list[str] = dataclass_field(default_factory=list)  # requested names (as given) not in the grid
    other_errors: list[str] = dataclass_field(default_factory=list)  # non-field problems, e.g. grid not found
    offered_fields: list[str] = dataclass_field(default_factory=list)  # technical names seen in grid, deduped, ordered
    hint: str | None = None  # extra sentence for the failure message (Web GUI: the grid was not read to its end)
    offered_partial: bool = False  # the offered list stems from a grid that was not read to its end


def _dedupe_keep_order(names: list[str]) -> list[str]:
    """Remove duplicates from ``names`` while keeping first-seen order."""
    return list(dict.fromkeys(names))


def _format_offered_fields(offered: list[str]) -> str:
    """Join offered field names, capped at 50 with a '… (+N more)' suffix. Empty list -> empty string."""
    shown = ", ".join(offered[:_SE16N_MAX_OFFERED_FIELDS])
    extra = len(offered) - _SE16N_MAX_OFFERED_FIELDS
    if extra > 0:
        shown += f", … (+{extra} more)"
    return shown


def _filter_fill_failure(fill: _FilterFillResult, table: str, now: datetime) -> SE16Result:
    """Build the failure result for filters that could not be applied (the query is not run)."""
    warnings = [f"Field '{name}' not found in SE16N selection criteria" for name in fill.unapplied_fields]
    warnings.extend(fill.other_errors)
    if not fill.unapplied_fields:
        error = "Could not apply filters: " + "; ".join(fill.other_errors)
        if fill.hint:
            error += f" {fill.hint}"
        return _empty_failure(error, table, now, filter_warnings=warnings)

    names = ", ".join(f"'{name}'" for name in fill.unapplied_fields)
    error = f"Filter field(s) {names} not available as SE16N selection criteria for table {table}."
    offered = _format_offered_fields(fill.offered_fields)
    if offered:
        label = "Offered fields (first part of the grid)" if fill.offered_partial else "Offered fields"
        error += f" {label}: {offered}."
    error += (
        " A field can exist in the table without being an SE16N selection field; use sap-adt `run_query` if available."
    )
    if fill.hint:
        error += f" {fill.hint}"
    return _empty_failure(error, table, now, filter_warnings=warnings)


@dataclass
class _GridRow:
    """One row of the SE16N selection-criteria grid as read from the Web GUI DOM."""

    row_index: int
    label: str
    field_name: str | None  # upper-case technical name; None when the column is not in the DOM
    fillable: bool  # the From-Value cell is an input (SE16N offers the field for selection)
    element_id: str | None
    selector: str | None


@dataclass
class _FilterPlan:
    """Which grid row each requested filter goes into, plus the filters that cannot be placed."""

    targets: list[tuple[str, str, _GridRow]] = dataclass_field(default_factory=list)  # (requested, value, row)
    result: _FilterFillResult = dataclass_field(default_factory=_FilterFillResult)


def _plan_se16n_filters(
    rows: list[_GridRow],
    filters: dict[str, str],
    field_order: dict[str, int] | None,
    table: str,
    possibly_truncated: bool = False,
) -> _FilterPlan:
    """Decide which selection row each filter belongs to, without trusting positions blindly.

    SE16N does not offer every SE11 field as a selection field, so SE11 positions can be shifted
    against the grid (#924). Therefore:

    * when every row shows its technical name, filters are matched **by name**, and the offered
      fields come from the grid;
    * when the technical names are not in the DOM, the SE11 order is used only if the grid has
      exactly as many rows as SE11 has fields; any other count means a field was left out,
      positions cannot be trusted, and nothing is filled.

    ``rows`` are the rows of the page of the grid that is shown; a field further down the table is not
    among them. When the grid has no empty padding row left (``possibly_truncated``) or SE11 lists more
    fields than the grid shows, the failure says so (``hint``). :func:`_fill_se16n_filters_webgui` scrolls
    the grid when every row shows its technical name; it calls this function (which does not scroll) only
    when the names are not readable.
    """
    plan = _FilterPlan()
    result = plan.result
    if not rows:
        result.other_errors.append("SE16N selection criteria grid has no rows")
        return plan

    truncation_hint: str | None = None
    if possibly_truncated or (field_order and len(field_order) > len(rows)):
        truncation_hint = (
            f"SAP Web GUI renders only the first rows of the grid ({len(rows)} here) and does not scroll it, "
            f"so a field further down table {table} cannot be reached."
        )

    if all(row.field_name for row in rows):
        by_name = {str(row.field_name): row for row in rows if row.fillable}
        rendered = {str(row.field_name) for row in rows}
        result.offered_fields = _dedupe_keep_order([str(row.field_name) for row in rows if row.fillable])
        for name, value in filters.items():
            row = by_name.get(name.upper())
            if row is None:
                result.unapplied_fields.append(name)
            else:
                plan.targets.append((name, value, row))
        # Only a field that is absent from the rendered rows can be "further down"; a rendered row that
        # merely has no input (the client field) is not.
        if truncation_hint and any(name.upper() not in rendered for name in result.unapplied_fields):
            result.hint = truncation_hint
        return plan

    # Technical names are not readable from the DOM: fall back to the SE11 order, but only if it provably fits.
    result.hint = truncation_hint
    if not field_order:
        result.other_errors.append(
            "SE16N does not show technical field names in the page and the SE11 field list is unavailable, "
            "so the filter row cannot be verified"
        )
        return plan
    if len(rows) != len(field_order):
        result.other_errors.append(
            f"SE16N offers {len(rows)} selection rows for table {table} "  # lang-ok: our own message
            f"but SE11 lists {len(field_order)} fields; "
            "row positions may not match field names, so no filter was applied"
        )
        return plan
    by_index = {row.row_index: row for row in rows}
    result.offered_fields = [
        name for name, position in field_order.items() if (row := by_index.get(position)) is not None and row.fillable
    ]
    for name, value in filters.items():
        position = field_order.get(name.upper())
        row = by_index.get(position) if position is not None else None
        if row is None or not row.fillable:
            result.unapplied_fields.append(name)
        else:
            plan.targets.append((name, value, row))
    return plan


def _parse_grid_rows(raw_rows: Any) -> list[_GridRow]:
    """Convert the rows returned by ``read_se16n_selection_rows.js`` into ``_GridRow`` objects.

    The grid is padded with empty rows (no label, no name, no input); those are not fields and are dropped.
    """
    rows: list[_GridRow] = []
    for raw in raw_rows or []:
        label = str(raw.get("label") or "")
        field_name = str(raw["fieldName"]).upper() if raw.get("fieldName") else None
        fillable = bool(raw.get("fillable"))
        if not (label or field_name or fillable):
            continue
        rows.append(
            _GridRow(
                row_index=int(raw["rowIndex"]),
                label=label,
                field_name=field_name,
                fillable=fillable,
                element_id=raw.get("elementId"),
                selector=raw.get("selector"),
            )
        )
    return rows


_SE16N_GRID_CELL_SELECTOR = '[role="grid"] [lsdata*="GS_SELFIELDS-"]'

_GridPage = tuple[list[_GridRow], bool]  # the rows of the page shown, and whether it ends in empty padding rows


async def _focus_selection_grid(backend: WebGuiBackend, rows: list[_GridRow]) -> bool:
    """Put the focus into the selection grid, so that PageDown scrolls it and not the page.

    Clicks the From-Value input of the first fillable row of the page (id first, then selector, like
    :func:`_fill_filter_by_locator`); when there is none or the clicks miss, any cell of the grid.

    Returns:
        True if a click hit an element.
    """
    row = next((candidate for candidate in rows if candidate.fillable), None)
    if row is not None:
        selectors = [f'[id="{row.element_id}"]'] if row.element_id else []
        if row.selector:
            selectors.append(row.selector)
        for selector in selectors:
            if await backend.click_element(selector):
                return True
    return bool(await backend.click_element(_SE16N_GRID_CELL_SELECTOR))


async def _read_selection_page(backend: WebGuiBackend, read_js: str) -> _GridPage | str:
    """Read the page of the selection grid that is shown now.

    Returns:
        ``(rows, has_padding)``, or an error text when the grid cannot be read or a row has no technical name.
    """
    grid = await backend.evaluate_javascript(read_js, {})
    if not grid.get("success"):
        return str(grid.get("error", "Could not read the SE16N selection grid"))
    rows = _parse_grid_rows(grid.get("rows"))
    if not rows or not all(row.field_name for row in rows):
        return "SE16N selection rows could not be read after scrolling, so no filter was applied"
    return rows, bool(grid.get("hasPaddingRows"))


async def _scroll_selection_grid(backend: WebGuiBackend, read_js: str, rows: list[_GridRow]) -> _GridPage | str | None:
    """Scroll the grid down by one page with PageDown.

    The grid is read again when the page looks unchanged (it may not be rendered yet); a page that is still
    the same means the end of the grid.

    Returns:
        The new page, an error text, or None at the end of the grid.
    """
    if not await _focus_selection_grid(backend, rows):
        return "Could not focus the SE16N selection grid to scroll it, so no filter was applied"
    await backend.press_key("PageDown")
    await backend.wait(500)
    page = await _read_selection_page(backend, read_js)
    if isinstance(page, str) or [row.field_name for row in page[0]] != [row.field_name for row in rows]:
        return page
    await backend.wait(1000)
    page = await _read_selection_page(backend, read_js)
    if isinstance(page, str) or [row.field_name for row in page[0]] != [row.field_name for row in rows]:
        return page
    return None


@dataclass
class _ScrollScan:
    """The requested filters and which of them the scan through the pages of the selection grid has decided."""

    filters: dict[str, str]
    undecided: list[str] = dataclass_field(init=False)  # requested names, filter order
    unapplied: set[str] = dataclass_field(default_factory=set)  # found, but the row has no input
    offered: list[str] = dataclass_field(default_factory=list)  # fillable names seen; pages may overlap
    other_errors: list[str] = dataclass_field(default_factory=list)

    def __post_init__(self) -> None:
        self.undecided = list(self.filters)

    async def process(self, backend: WebGuiBackend, rows: list[_GridRow]) -> bool:
        """Decide the undecided fields found on this page and fill them, top row first.

        Returns:
            True if a field was filled (the Tab after it may have shifted the grid).
        """
        self.offered.extend(str(row.field_name) for row in rows if row.fillable)
        by_name = {str(row.field_name): row for row in rows}
        found = sorted(
            ((name, by_name[name.upper()]) for name in self.undecided if name.upper() in by_name),
            key=lambda item: item[1].row_index,
        )
        filled = False
        for name, row in found:
            self.undecided.remove(name)
            if not row.fillable:
                self.unapplied.add(name)
            elif await _fill_filter_by_locator(backend, row.element_id, row.selector, self.filters[name], name):
                filled = True
            else:
                self.other_errors.append(f"Found the selection row for {name} but filling it failed")
        return filled


async def _fill_se16n_filters_by_name_scrolling(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    backend: WebGuiBackend,
    read_js: str,
    table: str,
    filters: dict[str, str],
    first_page: list[_GridRow],
    first_has_padding: bool,
) -> _FilterFillResult:
    """Fill the filters by technical name, scrolling the selection grid page by page until all are decided.

    The grid shows one page of rows (16 on a typical system; a wide table has hundreds of rows) and the row
    index of a page is relative to it, so element ids are valid only for the page shown. A value typed into a
    row stays when the grid scrolls on. The scan stops when every requested field is decided (filled, or found
    without an input), at the end of the grid (padding rows, or a PageDown that shows the same page) or after
    ``_SE16N_MAX_SELECTION_PAGES`` pages.
    """
    scan = _ScrollScan(filters)
    result = _FilterFillResult()
    rows, has_padding = first_page, first_has_padding
    pages = 1  # pages reached by PageDown, the first one included
    reached_end = False
    failed = False
    while True:
        filled = await scan.process(backend, rows)
        if not scan.undecided:
            break
        if has_padding:
            reached_end = True
            break
        step: _GridPage | str | None
        if filled:
            # The Tab after a fill may have shifted the grid: read this page again before scrolling on.
            step = await _read_selection_page(backend, read_js)
        elif pages >= _SE16N_MAX_SELECTION_PAGES:
            result.hint = (
                f"The SE16N selection grid of table {table} was not read to its end "  # lang-ok: our own message
                f"(stopped after {_SE16N_MAX_SELECTION_PAGES} pages)."
            )
            break
        else:
            step = await _scroll_selection_grid(backend, read_js, rows)
            pages += 1
            if step is None:
                reached_end = True
                break
        if isinstance(step, str):
            scan.other_errors.append(step)
            failed = True
            break
        rows, has_padding = step
    if not failed:  # after an error the remaining fields are not known to be missing
        scan.unapplied.update(scan.undecided)
    result.unapplied_fields = [name for name in filters if name in scan.unapplied]
    result.other_errors = scan.other_errors
    result.offered_fields = _dedupe_keep_order(scan.offered)
    result.offered_partial = not reached_end
    return result


async def _fill_se16n_filters_webgui(
    backend: WebGuiBackend, table: str, filters: dict[str, str], field_order: dict[str, int] | None
) -> _FilterFillResult:
    """Fill the SE16N selection criteria on the Web GUI backend, placing each filter by field name.

    Reads the grid rows (index, technical name, input element) from the DOM. When every row shows its
    technical name, the grid is scrolled page by page until each filter is placed
    (:func:`_fill_se16n_filters_by_name_scrolling`). Otherwise the filters are planned on the rows of the
    first page (:func:`_plan_se16n_filters`). The inputs are filled through the protocol's
    ``fill_element_by_locator`` (click + type, which triggers the proper SAP events).

    Filters that cannot be placed, and fills that fail, are reported in the result; the caller must
    not run the query when the result is not clean.
    """
    read_js = backend.load_js("read_se16n_selection_rows.js")
    grid = await backend.evaluate_javascript(read_js, {})
    if not grid.get("success"):
        return _FilterFillResult(other_errors=[str(grid.get("error", "Could not read the SE16N selection grid"))])

    rows = _parse_grid_rows(grid.get("rows"))
    has_padding = bool(grid.get("hasPaddingRows"))
    if rows and all(row.field_name for row in rows):
        return await _fill_se16n_filters_by_name_scrolling(backend, read_js, table, filters, rows, has_padding)

    plan = _plan_se16n_filters(rows, filters, field_order, table, possibly_truncated=not has_padding)
    result = plan.result
    for name, value, row in plan.targets:
        if not await _fill_filter_by_locator(backend, row.element_id, row.selector, value, name):
            result.other_errors.append(f"Found the selection row for {name} but filling it failed")
    return result


async def _execute_se16_query(  # pylint: disable=too-many-locals,too-many-branches,too-many-return-statements,too-many-statements
    backend: WebGuiBackend,
    table: str,
    filters: dict[str, str] | None,
    max_hits: int,
    ctx: Context | None = None,
) -> SE16Result:
    """
    Execute SE16N query and collect results.

    Args:
        backend: WebGuiBackend instance
        table: Table name to query
        filters: Optional filter dict {field_name: value}
        max_hits: Maximum rows to return
        ctx: FastMCP context for progress reporting

    Returns:
        SE16Result with collected data
    """
    now = datetime.now(UTC)
    filter_warnings: list[str] = []
    # Resolved once, outside every try: an UnsupportedLanguageError must reach the caller
    t = lang.current("sap_se16_query")

    # If filters are provided, get field order from SE11 FIRST
    # (before navigating to SE16N, since SE11 lookup changes the screen).
    # It is only used when SE16N's grid does not show technical field names, and then only if
    # the row count matches (#924); otherwise filters are placed by the name read from the grid.
    field_order: dict[str, int] | None = None
    if filters:
        logger.info("Getting field order from SE11", extra={"table": table})
        field_order = await _get_field_order_from_se11(backend, table, t)
        if field_order is None:
            logger.warning("Could not get field order from SE11, filters may not work")

    # Navigate to SE16N (enter_transaction prepends /n, so a result list of a previous query is left)
    tx_result = await backend.enter_transaction("SE16N")
    if not tx_result.success:
        return _empty_failure(f"Failed to navigate to SE16N: {tx_result.error}", table, now)

    await backend.wait(1000)  # Wait for SE16N screen to render

    # Fill table name - with validation trigger if filters are provided
    fill_error: str | None = None
    if filters:
        fill_error = await _type_table_name_with_validation(backend, table, t)
        if not fill_error:
            await _wait_for_grid_rows(backend, t, timeout_seconds=5)
            fill = await _fill_se16n_filters_webgui(backend, table, filters, field_order)
            if fill.unapplied_fields or fill.other_errors:
                logger.warning(
                    "WebGUI filters could not be applied, not running the query",
                    extra={"unapplied": fill.unapplied_fields, "errors": fill.other_errors},
                )
                return _filter_fill_failure(fill, table, now)
            # Re-fill table name after filter filling — filter input via
            # page.keyboard could have corrupted it (fixes #289, #290)
            refill_error = await _fill_se16n_table_name(backend, table, t)
            if refill_error:
                logger.warning("Could not re-fill table name after filters", extra={"error": refill_error})
    else:
        fill_error = await _fill_se16n_table_name(backend, table, t)

    if fill_error:
        return _empty_failure(fill_error, table, now)

    # Set max hits
    await _fill_se16n_max_hits(backend, max_hits, t)

    # Best-effort: click table name field to move focus out of filter grid
    # (focus in filter grid can interfere with F8).
    try:
        selector = ", ".join(f"input[title*='{v}'], input[aria-label*='{v}']" for v in t.se16.table_label)
        await backend.click_element(selector)
        await backend.wait(200)
    except Exception:  # pylint: disable=broad-exception-caught
        pass  # Best effort - continue with F8

    # Execute query (F8) and wait for results
    logger.info("Executing query with F8")
    await backend.press_key("F8")
    await backend.wait(3000)

    # Get snapshot to check for errors and parse results
    snapshot = AriaSnapshot(await backend.get_snapshot())
    snapshot_str = str(snapshot)

    # Check for table not found errors
    if table_error := _check_table_not_found(snapshot_str, table, t):
        # Log first 500 chars of snapshot for debugging
        logger.warning("Check failed", extra={"snapshot_preview": snapshot_str[:500]})
        return _empty_failure(table_error, table, now)

    # Parse hit count and columns
    total_hits = parse_se16_hit_count(snapshot, t)
    columns = parse_se16_columns(snapshot, t)

    if not columns:
        return _empty_failure(
            "Could not parse column headers from SE16N results",
            table,
            now,
            total_hits=total_hits,
        )

    # Check if we're still on selection screen (parsed filter grid instead of results)
    if _check_selection_screen_columns(columns, t):
        # Distinguish empty table from non-existent table:
        # SAP shows "No values found" / "Keine Werte gefunden" for existing tables with no data
        if _check_no_entries_found(snapshot_str, t):
            logger.info("Table exists but has no entries", extra={"table": table})
            return SE16Result(
                table=table,
                total_hits=0,
                returned_rows=0,
                truncated=False,
                columns=[],
                rows=[],
                filter_warnings=filter_warnings,
                retrieved_at=now,
            )
        logger.info("Parsed selection screen columns, table likely doesn't exist", extra={"table": table})
        return _empty_failure(
            f"Table '{table}' not found in SAP (still on selection screen)",  # lang-ok: our own message
            table,
            now,
        )

    # Handle empty results
    if total_hits == 0:
        return SE16Result(
            table=table,
            total_hits=0,
            returned_rows=0,
            truncated=False,
            columns=columns,
            rows=[],
            filter_warnings=filter_warnings,
            retrieved_at=now,
        )

    # The rows are keyed by the technical field names, like the desktop server does (#78)
    columns = await _read_technical_column_names(backend, columns)

    # Focus grid and collect all rows with pagination
    await _focus_grid(backend)
    rows = [SE16Row(data=row) for row in await _collect_rows_with_pagination(backend, total_hits, columns, t, ctx)]

    return SE16Result(
        table=table,
        total_hits=total_hits,
        returned_rows=len(rows),
        truncated=total_hits >= max_hits,
        columns=columns,
        rows=rows,
        filter_warnings=filter_warnings,
        retrieved_at=now,
    )


# =============================================================================
# MCP Tool Registration
# =============================================================================


def register_se16_tools(mcp: FastMCP) -> None:
    """Register SE16 tools with the MCP server."""

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            open_world_hint=False,
        ),
        description=(
            "Query SAP table data via SE16N (Data Browser). "
            "If sap-adt is available, prefer its run_query tool for simple queries. "
            "USE THIS for complex queries with dynamic filtering or when ADT is unavailable.\n\n"
            "**Filters:** If a filter cannot be applied (e.g. the field is unknown or not offered by "
            "SE16N), the call fails before running the query; the error lists the SE16N selection "
            "fields when they could be read. On the WebGUI backend a filter goes into the row whose "
            "technical name matches; the selection grid is scrolled until that row is found, so a field "
            "of a wide table can be filtered, too.\n\n"
            "**Performance:** ~7 rows/second due to pagination.\n"
            "- 100 rows: ~14 seconds\n"
            "- 500 rows: ~1.5 minutes\n"
            "- 1000 rows: ~2.5 minutes\n"
            "- 5000 rows: ~12 minutes\n\n"
            "For large results, use `output_file` to write JSON to disk and receive a summary."
        ),
    )
    async def sap_se16_query(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        ctx: Context,
        table: str,
        filters: dict[str, str] | None = None,
        max_hits: int = DEFAULT_MAX_HITS,
        output_file: str | None = None,
        session: str | None = None,
        agent_id: str | None = None,
    ) -> SE16Result | SE16FileSummary:
        """
        Query SAP table data via SE16N.

        Args:
            ctx: FastMCP context (injected)
            table: Table name to query (e.g., "MARA", "T000", "TSTC")
            filters: Optional filter dict {field_name: value} - uses technical field names. A field that is
                unknown or not offered by SE16N makes the call fail (both backends). On the WebGUI backend
                the selection grid is scrolled until the row of the field is found.
            max_hits: Maximum rows to return (default 100)
            output_file: If provided, write full results to this JSON file within the
                configured output directory (OUTPUT_DIR, default: current working
                directory) and return summary
            session: Session ID (e.g., "s1", "s2"). None uses primary session.
            agent_id: Agent identifier for binding check. Optional.

        Returns:
            SE16Result with all rows (inline), or
            SE16FileSummary with file path and preview (when output_file provided)
        """
        if output_file:
            try:
                output_path = resolve_output_file_path(output_file)
            except ValueError as e:
                now = datetime.now(UTC)
                return SE16Result.failure(
                    error=str(e),
                    table=table,
                    total_hits=0,
                    returned_rows=0,
                    truncated=False,
                    columns=[],
                    rows=[],
                    retrieved_at=now,
                )
        else:
            output_path = None

        try:
            backend = await get_backend(session=session, agent_id=agent_id, tool_name="sap_se16_query")
        except ValueError as e:
            now = datetime.now(UTC)
            return SE16Result.failure(
                error=f"Session error: {e}",
                table=table,
                total_hits=0,
                returned_rows=0,
                truncated=False,
                columns=[],
                rows=[],
                retrieved_at=now,
            )

        logger.info("Querying table", extra={"table": table, "max_hits": max_hits})

        result = await _execute_se16_query(backend, table, filters, max_hits, ctx)

        # Write to file if requested
        if output_file and output_path and result.success:
            try:
                output_path = write_json_output_file(output_file, result.model_dump(mode="json"))
            except (ValueError, OSError) as e:
                failure_payload = result.model_dump(mode="python")
                failure_payload["success"] = False
                failure_payload["error"] = str(e)
                return SE16Result(**failure_payload)

            return SE16FileSummary(
                success=True,
                output_file=str(output_path.absolute()),
                table=result.table,
                total_hits=result.total_hits,
                returned_rows=result.returned_rows,
                truncated=result.truncated,
                columns=result.columns,
                sample_rows=result.rows[:5],  # First 5 rows as preview
                filter_warnings=result.filter_warnings,
            )

        return result
