# Models

This directory contains the Pydantic models and the settings of the SAP Web GUI MCP Server.

## Module Structure

```
models/
├── __init__.py              # Package exports
├── config.py                # Settings (pydantic-settings) and the systems.json loader
├── base.py                  # ToolResult base class, TCode type, PopupInfo
├── sap_results.py           # Core SAP result models (LoginResult, StatusBarInfo, TableData, ...)
├── screen_state.py          # Selection screen state models
├── quick_report_models.py   # QuickReportResult, ScreenClassification
├── abapgit_models.py        # abapGit results
├── se16_models.py           # One result module per transaction tool
│   ...                      # (se09, se11, se24, se37, se38, se93, sm30, sm37, slg1, spro, st22, ...)
└── README.md                # This file
```

## Configuration (`config.py`)

The `SapGuiSettings` class uses [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) to
load the server settings from environment variables and from a `.env` file in the working directory. Unknown
variables are ignored.

### Available Settings

| Environment Variable   | Type | Default                      | Description                                                                  |
| ---------------------- | ---- | ---------------------------- | ---------------------------------------------------------------------------- |
| `SAP_URL`              | str  | `""`                         | Fallback SAP Web GUI URL, used when the system has no `host`                 |
| `OUTPUT_DIR`           | str  | `""`                         | Directory that `output_file` arguments are sandboxed to (empty: working dir) |
| `BROWSER_MODE`         | enum | `connect`                    | `connect` (existing Chrome via CDP) or `launch` (Playwright)                 |
| `BROWSER_TYPE`         | enum | `chromium`                   | `chromium`, `firefox`, or `webkit`                                           |
| `BROWSER_HEADLESS`     | bool | `false`                      | Run the browser without a window                                             |
| `CDP_URL`              | str  | `http://localhost:9222`      | Chrome DevTools Protocol URL for connect mode                                |
| `CHROME_PATH`          | str  | `""`                         | Explicit path to the Chrome binary (empty: auto-detect)                      |
| `CHROME_USER_DATA_DIR` | str  | `<tempdir>/chrome-debug`     | User data directory of an auto-launched Chrome                               |
| `GITHUB_PAT`           | str  | `""`                         | GitHub token for `log_feedback` issues and abapGit pulls                     |
| `GITHUB_USER`          | str  | `""`                         | GitHub user name for abapGit (falls back to `x-access-token`)                |
| `GITHUB_REPO`          | str  | `Hochfrequenz/sapwebgui.mcp` | Repository that receives feedback issues                                     |
| `ABAPGIT_PAT`          | str  | unset                        | Separate token for abapGit, overrides `GITHUB_PAT` there                     |
| `LOG_FORMAT`           | str  | `""`                         | `json` for JSON logs                                                         |
| `LOG_LEVEL`            | str  | `INFO`                       | `DEBUG`, `INFO`, `WARNING`, or `ERROR`                                       |

SAP credentials and the login language (user, password, client, language) are loaded from `~/.config/sap-mcp/systems.json`
(or the path set via the `SAP_CONFIG_FILE` env var) by `get_sap_config()`. See the
[sap-mcp-config](https://github.com/Hochfrequenz/sap-mcp-config) package.

### Usage

```python
from sapwebguimcp.models import get_settings

settings = get_settings()
print(settings.sap_url)
print(settings.browser_mode)
```

### Adding New Settings

1. Add a new field to `SapGuiSettings`:

```python
class SapGuiSettings(BaseSettings):
    # ... existing fields ...

    my_new_setting: str = Field(
        default="default_value",
        description="Description of the setting",
        json_schema_extra={"env": "MY_NEW_SETTING"},
    )
```

2. Update the `__all__` export if adding new public classes.
3. Add the variable to the table above, to the README's environment variable table and to `.env.example`.

## Backend Abstraction (`backend/`)

Tools get the backend via `get_backend()` instead of touching Playwright directly. It returns the
`WebGuiBackend`; there is no shared protocol class.

### Usage

```python
from sapwebguimcp.backend.manager import get_backend

backend = await get_backend(session=session, agent_id=agent_id, tool_name="my_tool")
await backend.enter_transaction("SE16")
snapshot = await backend.get_snapshot()
```

### Architecture

- **`backend/webgui/backend.py`** — `WebGuiBackend` (Playwright-based implementation)
- **`backend/manager.py`** — `BackendManager` singleton, `get_backend()` entry point
- **`backend/webgui/browser.py`** — `BrowserManager` for the low-level browser lifecycle

## Type Hints

All models use proper type hints for mypy strict mode. When adding new models:

- Use `Optional[T]` for nullable types
- Use `list[T]` instead of `List[T]` (Python 3.9+)
- Add `__all__` exports for public API
- Run `uv run --group type_check mypy --show-error-codes src/sapwebguimcp --strict` to verify type correctness
