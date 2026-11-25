"""
Parser for SE37 (Function Builder) ARIA snapshots.

Extracts function module metadata from SE37 display screens, handling:
- Function module name from heading
- Import/Export/Changing/Tables parameters from grids
- Exceptions from grid
- German and English label support
"""

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sapwebguimcp.backend.webgui.parsers.aria_fields import textbox_value, unescape_yaml_name
from sapwebguimcp.backend.webgui.types import AriaSnapshot
from sapwebguimcp.lang.schema import LanguagePack
from sapwebguimcp.lang.text import Text, compiled
from sapwebguimcp.models.se37_models import (
    SE37Entry,
    SE37Error,
    SE37Exception,
    SE37Parameter,
    SE37ParameterCategory,
    SE37TypingMethod,
)

logger = logging.getLogger(__name__)

__all__ = [
    "parse_se37_snapshot",
    "parse_se37_parameters_snapshot",
    "parse_se37_exceptions_snapshot",
    "parse_se37_properties_snapshot",
    "SE37Properties",
    "SE37TabSnapshots",
]

# =============================================================================
# Regex Patterns
# =============================================================================

_HEADING_TEXT = re.compile(r'heading "([^"]*)"')
_NAME_CHARS = r"[A-Za-z0-9_/ ]+"
"""Heading name group: the module name, possibly preceded by a type word."""


def _param_row_pattern(t: LanguagePack) -> re.Pattern[str]:
    """Parameter row: ``PARAM_NAME LIKE|TYPE REF_TYPE [DEFAULT] [optional_flag] Description Button``."""
    return compiled(
        r'(?i)row "(?P<name>[A-Z0-9_]+)\s+(?P<decl>LIKE|TYPE)\s+(?P<ref>[A-Z0-9_/-]+)'
        r"(?:\s+(?P<default>\S+))?"
        r"(?:\s+)?"
        r'(?P<desc>[^"]*?)'
        rf'(?:\s+{t.common.display.alt})?"\s*:'
    )


def _exception_row_pattern(t: LanguagePack) -> re.Pattern[str]:
    """Exception row: ``EXCEPTION_NAME Description Button``."""
    return compiled(rf'(?i)row "(?P<name>[A-Z0-9_]+)\s+(?P<desc>[^"]+?)(?:\s+{t.common.display.alt})?"\s*:')


# Check if checkbox is checked
_CHECKBOX_CHECKED_PATTERN = re.compile(r"checkbox[^]]*\[checked\]", re.IGNORECASE)

# Tab selection pattern
_TAB_SELECTED_PATTERN = re.compile(r'tab "(?P<tab>[^"]+)"\s*\[selected\]', re.IGNORECASE)


# =============================================================================
# Positional (cell based) grid parsing
# =============================================================================
#
# The accessible name of a grid row is the concatenation of its cells, which cannot tell an empty default
# value from a missing one, loses cells whose text contains a double quote, and (in the live DOM) repeats the
# column title for cells without a value. So the parameter and exception grids are read cell by cell.

_ROW_LINE = re.compile(r"^(?P<indent>\s*)- '?row\b")
_CELL_LINE = re.compile(
    r"^(?P<indent>\s*)- '?(?P<kind>gridcell|columnheader)(?: \"(?P<name>.*)\")?(?: \[[^\]]*\])*'?:?\s*$"
)

# Cell layout after the three leading columns (name, typing, reference type), per parameter category
_PARAM_TAIL_LAYOUT: dict[str, tuple[str, ...]] = {
    "import": ("default", "optional", "by_value", "short_text", "long_text"),
    "changing": ("default", "optional", "by_value", "short_text", "long_text"),
    "export": ("by_value", "short_text", "long_text"),
    "tables": ("optional", "short_text", "long_text"),
}


@dataclass
class _GridCell:
    """One cell of a grid row: its accessible name, and the state of a checkbox inside it (None: no checkbox)."""

    text: str
    checked: bool | None = None


def _grid_rows(snapshot: str) -> tuple[list[str], list[list[_GridCell]]]:
    """Split a grid snapshot into its column titles and its data rows (each a list of cells).

    A cell whose accessible name is just the title of its column is empty: the live DOM labels empty
    cells with their column title.
    """
    headers: list[str] = []
    rows: list[list[_GridCell]] = []
    row_indent = -1
    cells: list[_GridCell] | None = None
    cell_indent = -1
    for line in snapshot.splitlines():
        row_match = _ROW_LINE.match(line)
        if row_match:
            cells = []
            rows.append(cells)
            row_indent = len(row_match.group("indent"))
            cell_indent = -1
            continue
        if cells is None:
            continue
        indent = len(line) - len(line.lstrip())
        if line.strip() and indent <= row_indent:
            cells = None
            continue
        cell_match = _CELL_LINE.match(line)
        if cell_match:
            quoted = line.lstrip().startswith("- '")
            name = unescape_yaml_name(cell_match.group("name") or "", quoted)
            if cell_match.group("kind") == "columnheader":
                headers.append(name)
            else:
                cells.append(_GridCell(text=name))
                cell_indent = len(cell_match.group("indent"))
            continue
        if cells and indent > cell_indent >= 0 and "- checkbox" in line:
            cells[-1].checked = "[checked]" in line
    data_rows: list[list[_GridCell]] = []
    for row in rows:
        for index, cell in enumerate(row):
            if index < len(headers) and cell.text.strip() == headers[index].strip():
                cell.text = ""
        if row:
            data_rows.append(row)
    return headers, data_rows


def _cell_text(cells: list[_GridCell], index: int) -> str:
    return cells[index].text.strip() if index < len(cells) else ""


_TYPING_METHODS: tuple[SE37TypingMethod, ...] = ("LIKE", "TYPE", "TYPE REF TO")


def _typing_method(cell_text: str) -> SE37TypingMethod | None:
    """The typing method of a parameter row (LIKE, TYPE, TYPE REF TO); None for an untyped parameter."""
    text = " ".join(cell_text.upper().split())
    return next((method for method in _TYPING_METHODS if method == text), None)


def _parse_parameter_cells(snapshot: str, category: SE37ParameterCategory) -> list[SE37Parameter]:
    """Read the parameters of a tab grid cell by cell. Rows without a parameter name are padding."""
    layout = _PARAM_TAIL_LAYOUT[category]
    parameters: list[SE37Parameter] = []
    seen: set[str] = set()
    for cells in _grid_rows(snapshot)[1]:
        name = _cell_text(cells, 0)
        typing = _typing_method(_cell_text(cells, 1))
        # an untyped parameter has an empty typing cell; anything else in that cell is not a parameter row
        if not name or (typing is None and _cell_text(cells, 1)):
            continue
        # The grid renders only the visible rows, so the snapshots of several scroll positions are concatenated
        # and overlap: a parameter name is unique within a tab (#76)
        if name in seen:
            continue
        seen.add(name)
        tail = {key: cells[3 + i] for i, key in enumerate(layout) if 3 + i < len(cells)}
        default = tail["default"].text.strip() if "default" in tail else ""
        parameters.append(
            SE37Parameter(
                name=name,
                category=category,
                typing=typing,
                reference_type=_cell_text(cells, 2),
                default_value=default or None,
                optional=bool("optional" in tail and tail["optional"].checked),
                pass_by_value=bool("by_value" in tail and tail["by_value"].checked),
                description=tail["short_text"].text.strip() if "short_text" in tail else "",
            )
        )
    return parameters


def _parse_exception_cells(snapshot: str) -> list[SE37Exception]:
    """Read the exceptions of the Exceptions tab grid cell by cell."""
    exceptions: dict[str, SE37Exception] = {}
    for cells in _grid_rows(snapshot)[1]:
        name = _cell_text(cells, 0)
        if name and name not in exceptions:  # overlapping scroll positions, see _parse_parameter_cells
            exceptions[name] = SE37Exception(name=name, description=_cell_text(cells, 1))
    return list(exceptions.values())


# =============================================================================
# Properties (attributes) tab
# =============================================================================

_RADIO_LINE = re.compile(r"""^\s*- '?radio "(?P<label>(?:[^"\\]|\\.)*)"(?P<flags>(?: \[[^\]]*\])*)""")


@dataclass
class SE37Properties:
    """Header data of the properties (attributes) tab: what the parameter tabs do not carry."""

    function_group: str | None = None
    package: str | None = None
    description: str = ""
    is_rfc_enabled: bool = False


def _radio_checked(snapshot: str, label: Text) -> bool:
    """Whether the radio button labelled ``label`` is selected."""
    for line in snapshot.splitlines():
        match = _RADIO_LINE.match(line)
        if match and label.equals(match.group("label")):
            return "[checked]" in match.group("flags")
    return False


def parse_se37_properties_snapshot(snapshot: AriaSnapshot, t: LanguagePack) -> SE37Properties:
    """Parse the properties (attributes) tab: function group, package, short text and the RFC flag."""
    text = str(snapshot)
    return SE37Properties(
        function_group=textbox_value(text, t.se37.function_group_field) or None,
        package=textbox_value(text, t.se37.package_field) or None,
        description=textbox_value(text, t.se37.short_text_field) or "",
        is_rfc_enabled=_radio_checked(text, t.se37.rfc_radio),
    )


def _extract_function_module_name(snapshot: str, t: LanguagePack) -> str | None:
    """Extract function module name from heading (``Function Builder: Display RFC_READ_TABLE``)."""
    for heading in _HEADING_TEXT.finditer(snapshot):
        match = t.se37.display_title.search(heading.group(1), name=_NAME_CHARS)
        if match is not None and (tokens := match.group("name").split()):
            return tokens[-1].upper()
    return None


def _get_selected_tab(snapshot: str) -> str | None:
    """Get the currently selected tab name."""
    match = _TAB_SELECTED_PATTERN.search(snapshot)
    if match:
        return match.group("tab")
    return None


def _get_checkbox_flags(snapshot: str, match: re.Match[str], category: SE37ParameterCategory) -> tuple[bool, bool]:
    """Extract optional and pass_by_value flags from checkbox states."""
    row_start = match.start()
    row_end = snapshot.find("\n        - row", row_start + 1)
    if row_end == -1:
        row_end = len(snapshot)
    row_content = snapshot[row_start:row_end]
    checked_count = len(_CHECKBOX_CHECKED_PATTERN.findall(row_content))

    if category == "import":
        return checked_count >= 1, checked_count >= 2
    if category == "export":
        return False, checked_count >= 1
    if category == "tables":
        return checked_count >= 1, False
    if category == "changing":
        return checked_count >= 1, checked_count >= 2
    return False, False


def _parse_parameter_rows(snapshot: str, category: SE37ParameterCategory, t: LanguagePack) -> list[SE37Parameter]:
    """Parse parameter rows from a grid section."""
    if from_cells := _parse_parameter_cells(snapshot, category):
        return from_cells
    parameters: list[SE37Parameter] = []

    for match in _param_row_pattern(t).finditer(snapshot):
        name = match.group("name")
        typing_str = match.group("decl").upper()
        ref_type = match.group("ref")
        default = match.group("default")
        desc = re.sub(r"\s+$", "", match.group("desc").strip())
        typing = _typing_method(typing_str)
        optional, pass_by_value = _get_checkbox_flags(snapshot, match, category)

        parameters.append(
            SE37Parameter(
                name=name,
                category=category,
                typing=typing,
                reference_type=ref_type,
                default_value=default if default and default.strip() else None,
                optional=optional,
                pass_by_value=pass_by_value,
                description=desc,
            )
        )

    return parameters


def _parse_exception_rows(snapshot: str, t: LanguagePack) -> list[SE37Exception]:
    """Parse exception rows from exceptions grid."""
    from_cells = _parse_exception_cells(snapshot)
    # A grid with column headers is read cell by cell, even when it holds no exception: the regex fallback would
    # take the "E2E Time 157 ms" rows of the system information menu for exceptions (#76)
    if from_cells or _grid_rows(snapshot)[0]:
        return from_cells
    exceptions: list[SE37Exception] = []

    for match in _exception_row_pattern(t).finditer(snapshot):
        name = match.group("name")
        desc = match.group("desc").strip()

        # Skip if this looks like a parameter row (has LIKE/TYPE)
        if " LIKE " in match.group(0) or " TYPE " in match.group(0):
            continue

        # Skip the header row ("Ausnahme Kurztext Langtext"): its first column title is one ASCII
        # word and so looks like an exception name. Exception names are upper case, the column
        # title is not, so an exception literally named EXCEPTION / AUSNAHME is kept.
        if t.se37.exception_column.equals(name) and not name.isupper():
            continue

        exceptions.append(
            SE37Exception(
                name=name,
                description=desc,
            )
        )

    return exceptions


def _is_initial_se37_screen(snapshot: str, t: LanguagePack) -> bool:
    """Check if we're on the initial SE37 screen (no function module displayed)."""
    header_section = "\n".join(snapshot.split("\n")[:10])
    return any(f'heading "{variant}"' in header_section for variant in t.se37.initial_screen)


def _is_fm_not_found(snapshot: str, fm_name: str, t: LanguagePack) -> bool:
    """Check if function module was not found (status bar message)."""
    if t.se37.not_found.contains(snapshot):
        return True
    pattern = re.compile(rf"(?i:{re.escape(fm_name)})\s+{t.common.not_found.alt}")  # lang-ok: per-name pattern
    return pattern.search(snapshot) is not None


def parse_se37_parameters_snapshot(
    snapshot: AriaSnapshot, category: SE37ParameterCategory, t: LanguagePack
) -> list[SE37Parameter]:
    """
    Parse parameters from a SE37 tab snapshot.

    Args:
        snapshot: YAML accessibility snapshot from the Import/Export/Changing/Tables tab
        category: Which parameter category this is
        t: Language pack of the session

    Returns:
        List of parsed parameters
    """
    return _parse_parameter_rows(snapshot, category, t)


def parse_se37_exceptions_snapshot(snapshot: AriaSnapshot, t: LanguagePack) -> list[SE37Exception]:
    """
    Parse exceptions from a SE37 Exceptions tab snapshot.

    Args:
        snapshot: YAML accessibility snapshot from the Exceptions tab
        t: Language pack of the session

    Returns:
        List of parsed exceptions
    """
    return _parse_exception_rows(snapshot, t)


@dataclass
class SE37TabSnapshots:
    """Container for SE37 tab snapshots."""

    import_tab: AriaSnapshot | None = None
    export_tab: AriaSnapshot | None = None
    changing_tab: AriaSnapshot | None = None
    tables_tab: AriaSnapshot | None = None
    exceptions_tab: AriaSnapshot | None = None
    properties_tab: AriaSnapshot | None = None


def parse_se37_snapshot(
    snapshot: AriaSnapshot,
    fm_name: str,
    t: LanguagePack,
    tab_snapshots: SE37TabSnapshots | None = None,
) -> SE37Entry | SE37Error:
    """
    Parse SE37 function module display snapshot into structured data.

    Args:
        snapshot: The main YAML accessibility snapshot from browser_snapshot
        fm_name: The function module name being looked up
        t: Language pack of the session
        tab_snapshots: Optional container with snapshots from each tab

    Returns:
        SE37Entry on success, SE37Error on parse failure
    """
    now = datetime.now(UTC)

    # Check if we're on initial screen
    if _is_initial_se37_screen(snapshot, t):
        return SE37Error(
            function_module=fm_name,
            error=f"Function module '{fm_name}' not found - still on initial screen",
            retrieved_at=now,
        )

    # Check for not found message
    if _is_fm_not_found(snapshot, fm_name, t):
        return SE37Error(
            function_module=fm_name,
            error=f"Function module '{fm_name}' not found",
            retrieved_at=now,
        )

    # Extract function module name from heading
    found_fm = _extract_function_module_name(snapshot, t)
    if not found_fm:
        # Try to use provided name if we can't extract from heading
        found_fm = fm_name.upper()

    # Parse parameters from each tab if provided
    tabs = tab_snapshots or SE37TabSnapshots()
    import_params = parse_se37_parameters_snapshot(tabs.import_tab, "import", t) if tabs.import_tab else []
    export_params = parse_se37_parameters_snapshot(tabs.export_tab, "export", t) if tabs.export_tab else []
    changing_params = parse_se37_parameters_snapshot(tabs.changing_tab, "changing", t) if tabs.changing_tab else []
    tables_params = parse_se37_parameters_snapshot(tabs.tables_tab, "tables", t) if tabs.tables_tab else []
    exceptions = parse_se37_exceptions_snapshot(tabs.exceptions_tab, t) if tabs.exceptions_tab else []

    properties = parse_se37_properties_snapshot(tabs.properties_tab, t) if tabs.properties_tab else SE37Properties()

    return SE37Entry(
        function_module=found_fm,
        function_group=properties.function_group,
        package=properties.package,
        description=properties.description,
        is_rfc_enabled=properties.is_rfc_enabled,
        import_parameters=import_params,
        export_parameters=export_params,
        changing_parameters=changing_params,
        tables_parameters=tables_params,
        exceptions=exceptions,
        retrieved_at=now,
    )
