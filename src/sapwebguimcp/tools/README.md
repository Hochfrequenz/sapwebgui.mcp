# Tools

This directory contains the MCP tool definitions of the SAP Web GUI MCP Server. Every tool drives
SAP Web GUI in a Chrome browser through the `WebGuiBackend`.

## Module Structure

```
tools/
├── __init__.py             # Package exports (the register_* functions)
├── sap_tools.py            # Core tools: login, transaction, screen reading, forms, keyboard, sessions
├── session_tools.py        # Implementations of the sap_session_* tools
├── browser_tools.py        # Low-level browser escape hatches
├── se09_tools.py           # SE09 Transport Organizer lookup
├── se11_tools.py           # SE11 ABAP Dictionary lookup
├── se16_tools.py           # SE16N table data query
├── se24_tools.py           # SE24 Class Builder lookup
├── se24_edit_tools.py      # SE24 method editing
├── se37_tools.py           # SE37 Function Builder lookup
├── se37_edit_tools.py      # SE37 function module editing
├── se38_edit_tools.py      # SE38 report editing
├── se93_tools.py           # SE93 Transaction Maintenance lookup
├── sm30_tools.py           # SM30 table maintenance view lookup
├── sm37_tools.py           # SM37 background job lookup
├── slg1_tools.py           # SLG1 application log lookup
├── spro_tools.py           # SPRO IMG search
├── st22_tools.py           # ST22 short dump lookup
├── abapgit_tools.py        # abapGit pull and list, SE38 source reading
├── quick_report_tools.py   # Composite: TX -> fill -> F8 -> read result
├── catalog_tools.py        # Offline search: transactions
├── table_tools.py          # Offline search: tables
├── class_tools.py          # Offline search: classes
├── fm_tools.py             # Offline search: function modules
├── intent_tools.py         # log_intent
├── feedback_tools.py       # log_feedback
└── README.md               # This file
```

## Available Tools

The server registers these tools. `sap_get_capabilities` returns the same list with the full
descriptions at runtime.

### Core SAP Tools (`sap_tools.py`)

| Tool                                                                                                                  | Description                                                           |
| --------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `sap_login`, `sap_list_connections`                                                                                   | Log in with a system from `systems.json`; list the configured systems |
| `sap_transaction`                                                                                                     | Enter and execute a transaction code (auto-enables the OK-Code field) |
| `sap_get_capabilities`                                                                                                | Tool list plus the SAP knowledge base (`data/sap_knowledge.md`)       |
| `sap_get_screen_text`, `sap_get_screen_info`, `sap_get_form_fields`                                                   | Read the current screen                                               |
| `sap_discover_fields`, `sap_discover_buttons`, `sap_get_shortcuts`, `sap_lookup_fields`                               | Find fields, buttons and keyboard shortcuts                           |
| `sap_fill_form`, `sap_set_field`, `sap_set_checkbox`, `sap_set_radio_button`, `sap_select_dropdown`, `sap_select_tab` | Fill and operate form controls                                        |
| `sap_click_button`, `sap_press_key`, `sap_close_popup`                                                                | Press buttons and keys, dismiss popups                                |
| `sap_read_table`, `sap_click_table_cell`                                                                              | Read and click ALV grids and tables                                   |
| `sap_read_status_bar`, `sap_screenshot`                                                                               | Status bar message, screenshot                                        |
| `sap_session_status`, `sap_keepalive_start`, `sap_keepalive_stop`                                                     | Session state and keepalive                                           |
| `sap_session_list`, `sap_session_close`, `sap_session_bind`, `sap_session_release`, `sap_session_reset_to_primary`    | Multi-session management                                              |
| `sap_session_detach`                                                                                                  | Registered but not supported on the Web GUI (always returns an error) |
| `choose`                                                                                                              | Let the user pick from a list (for example a system), from FastMCP    |

### Specialized Transaction Tools (faster, return structured data)

| Tool                                                                 | File                 | Description                                 |
| -------------------------------------------------------------------- | -------------------- | ------------------------------------------- |
| `sap_se09_lookup`                                                    | `se09_tools.py`      | Transport requests                          |
| `sap_se11_lookup`                                                    | `se11_tools.py`      | Table and structure metadata                |
| `sap_se16_query`                                                     | `se16_tools.py`      | Table data via SE16N with pagination        |
| `sap_se24_lookup`, `sap_se24_edit`                                   | `se24_*.py`          | Class and interface metadata; edit a method |
| `sap_se37_lookup`, `sap_se37_edit`                                   | `se37_*.py`          | Function module signature; edit a module    |
| `sap_se38_edit`                                                      | `se38_edit_tools.py` | Edit a report                               |
| `sap_se93_lookup`                                                    | `se93_tools.py`      | Transaction metadata                        |
| `sap_sm30_lookup`                                                    | `sm30_tools.py`      | Table maintenance view entries (read-only)  |
| `sap_sm37_lookup`                                                    | `sm37_tools.py`      | Background jobs and logs                    |
| `sap_slg1_lookup`                                                    | `slg1_tools.py`      | Application logs                            |
| `sap_spro_search`                                                    | `spro_tools.py`      | Search the IMG for customizing activities   |
| `sap_st22_lookup`                                                    | `st22_tools.py`      | ABAP short dumps                            |
| `sap_abapgit_pull`, `sap_abapgit_list_repos`, `sap_read_se38_source` | `abapgit_tools.py`   | abapGit pull and list; read report source   |

### Composite Tool

| Tool               | File                    | Description                                                   |
| ------------------ | ----------------------- | ------------------------------------------------------------- |
| `sap_quick_report` | `quick_report_tools.py` | TX -> fill selection screen -> F8 -> classify and read result |

**Note:** Use the specialized tools instead of `sap_transaction('SExx')`. They are faster and return
structured Pydantic models instead of requiring manual screen parsing.

### Offline Catalog Tools (no SAP connection needed)

`search_transactions`, `search_tables`, `search_classes`, `search_function_modules`.

### Logging Tools

`log_intent` (the agent states what it is about to do) and `log_feedback` (technical feedback; it can
create a GitHub issue when `GITHUB_PAT` is set).

### Browser Tools (`browser_tools.py`)

Low-level escape hatches when the SAP tools do not work:

| Tool                    | Description                                |
| ----------------------- | ------------------------------------------ |
| `browser_snapshot`      | Get accessibility tree of page             |
| `browser_screenshot`    | Take screenshot (returns base64 PNG)       |
| `browser_click`         | Click element by selector                  |
| `browser_fill`          | Fill input field                           |
| `browser_keyboard`      | Send keyboard input                        |
| `browser_navigate`      | Navigate to URL                            |
| `browser_evaluate`      | Execute JavaScript                         |
| `browser_wait`          | Wait for element state (use with selector) |
| `browser_get_html`      | Get HTML content                           |
| `browser_select_option` | Select dropdown option                     |

## Adding New Tools

### 1. Create a New Tool Module

Create a new file in the `tools/` directory:

```python
# src/sapwebguimcp/tools/my_custom_tools.py
"""Custom tools for [your use case]."""

import logging

from fastmcp import FastMCP

from sapwebguimcp.backend.manager import get_backend

__all__ = ["register_my_custom_tools"]

logger = logging.getLogger(__name__)


def register_my_custom_tools(mcp: FastMCP) -> None:
    """Register custom tools with the MCP server."""

    @mcp.tool()
    async def my_tool(
        param1: str, param2: int | None = None,
        session: str | None = None, agent_id: str | None = None,
    ) -> str:
        """
        Description of what this tool does.

        Args:
            param1: Description of param1
            param2: Optional description of param2

        Returns:
            Status message indicating success or describing any issues.
        """
        backend = await get_backend(session=session, agent_id=agent_id, tool_name="my_tool")

        try:
            await backend.click_button(param1)
            return f"Success: {param1}"
        except Exception as e:
            logger.exception("Error in my_tool")
            return f"Error: {e}"
```

Real tools return a Pydantic result model (see `models/`) instead of a plain string; see
`ARCHITECTURE.md` for the SE99 example.

### 2. Register in server.py

Update `server.py` to include your new tools:

```python
from sapwebguimcp.tools.my_custom_tools import register_my_custom_tools

# After creating the mcp instance:
register_sap_tools(mcp)
register_browser_tools(mcp)
register_my_custom_tools(mcp)  # Add this line
```

### 3. Export in `__init__.py`

```python
from sapwebguimcp.tools.my_custom_tools import register_my_custom_tools

__all__ = [
    # ... existing exports ...
    "register_my_custom_tools",
]
```

### 4. Add Tests

Create `unittests/test_my_custom_tools.py`:

```python
"""Tests for custom tools."""

import pytest


class TestMyCustomTools:
    """Tests for my_custom_tools module."""

    @pytest.mark.anyio
    async def test_my_tool_success(self) -> None:
        """Test my_tool returns success."""
        # Your test implementation
        pass
```

## Tool Best Practices

### 1. Always Use Type Hints

```python
async def my_tool(
        required_param: str,
        optional_param: int | None = None,
        flag: bool = False,
) -> str:
```

### 2. Provide Comprehensive Docstrings

The docstring is what Claude sees when deciding which tool to use:

```python
async def sap_transaction(tcode: str) -> str:
    """
    Enter and execute an SAP transaction code.

    This tool will:
    1. Check if the OK-Code field is visible
    2. If not, attempt to enable it via Settings
    3. Enter the transaction code and execute it

    Args:
        tcode: Transaction code (e.g., VA01, MM03, SE80, SU01)

    Returns:
        Status message indicating success or describing any issues.
    """
```

### 3. Handle Errors Gracefully

```python
try:
    result = await page.click(selector)
    return f"Success: clicked {selector}"
except Exception as e:
    logger.exception("Error clicking element")
    return f"Error clicking {selector}: {e}"
```

### 4. Return Informative Messages

Tools should return messages that help Claude understand what happened:

```python
# Good
return f"Transaction {tcode} executed. Current page: {title}."

# Bad
return "Done"
```

### 5. Use Logging

```python
import logging

logger = logging.getLogger(__name__)

# In your tool:
logger.info("Starting transaction: %s", tcode)
logger.debug("Found OK-Code field: %s", okcode_field)
logger.exception("Error executing transaction")  # Includes stack trace
```

## Customizing SAP Selectors

The `SELECTORS` dictionary in `sap_tools.py` contains CSS selectors for SAP Web GUI elements.
You may need to customize these for your specific SAP version:

```python
from sapwebguimcp.tools.sap_tools import SELECTORS

# Override a selector
SELECTORS["okcode_field"] = 'input#myCustomOkCodeField'

# Or create your own selector dictionary
MY_SELECTORS = {
    **SELECTORS,
    "custom_button": 'button#myButton',
}
```

## Testing Tools

Run the offline tests with:

```bash
uv run --group tests python -m pytest unittests/ -m "not integration"
```

For coverage:

```bash
uv run --group coverage coverage run -m pytest -m "not integration"
```

## Debugging Tips

1. **Use browser_snapshot** to see the page structure
2. **Use browser_screenshot** to see what's on screen
3. **Check logs** - tools log their actions
4. **Try browser_evaluate** to run diagnostic JavaScript

Example debugging workflow:

```
Claude: I'll first take a snapshot to understand the page structure.
[calls browser_snapshot]

Claude: I can see the structure. Let me take a screenshot to verify visually.
[calls browser_screenshot]

Claude: Now I'll try clicking the element.
[calls browser_click with the right selector]
```
