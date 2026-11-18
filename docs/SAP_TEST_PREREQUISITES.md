# SAP Test Prerequisites

This document describes everything needed to run the integration tests on a fresh SAP system. The tests drive SAP Web GUI in a Chrome browser. Unit tests do not need any of this (`uv run --group tests python -m pytest unittests/ -m "not integration"`).

## SAP System Configuration

### SAP Web GUI

The ICF service `/sap/bc/gui/sap/its/webgui` must be active on the system, and the test user must be able to log on to it with user and password.

### User Permissions

The test user needs access to the following transactions:

| Transaction | Purpose                                       |
| ----------- | --------------------------------------------- |
| SE16        | Data Browser (table queries)                  |
| SE24        | Class Builder (class editor tests)            |
| SE37        | Function Builder (function module tests)      |
| SE38        | ABAP Editor (report editor tests)             |
| SE09        | Transport Organizer (transport request tests) |
| SE93        | Transaction Maintenance (tcode lookup tests)  |
| SM37        | Job Overview (background job tests)           |
| SLG1        | Application Log (log reader tests)            |
| SM30        | Table Maintenance (view maintenance tests)    |
| SPRO        | Customizing (IMG tree search tests)           |
| ST22        | ABAP Dumps (dump analysis tests)              |
| BP          | Business Partner (BDT screen tests)           |

### Test Objects

The required test objects are maintained in an abapGit repository:

**https://github.com/Hochfrequenz/Z_MCP_TEST_EDITABLE_WB_OBJECTS**

Install via abapGit pull, or create manually:

| Object                    | Transaction | Details                                                            |
| ------------------------- | ----------- | ------------------------------------------------------------------ |
| Report `ZTEST_MCP_EDIT`   | SE38        | Must contain `REPORT ZTEST_MCP_EDIT.` + `WRITE 'MCP test report'.` |
| Class `ZCL_TEST_MCP_EDIT` | SE24        | Public class with method `DO_SOMETHING`                            |

Creating these objects generates **transport requests** owned by the test user (needed for SE09 tests).

### abapGit test repositories

Two public GitHub repositories (`Hochfrequenz/...`) back the abapGit and edit tests. They must be registered in abapGit on the SAP system:

| Repository                         | Used by                                       |
| ---------------------------------- | --------------------------------------------- |
| `Z_PUBLIC_ABAPGIT_TEST_REPOSITORY` | abapGit pull and list tests                   |
| `Z_MCP_TEST_EDITABLE_WB_OBJECTS`   | edit tests, SE09 tests (provides the objects) |

`Z_PUBLIC_ABAPGIT_TEST_REPOSITORY` must not be pinned to a commit. The pull tests need the report `Z_ABAPGIT_PULL_MCP_SHORTCUT` ([repository](https://github.com/Hochfrequenz/Z_ABAPGIT_PULL_MCP_SHORTCUT)) installed on the system. The public repository is also available as a git submodule under `unittests/testdata/abapgit_repos/` (run `git submodule update --init` to fetch it).

### Optional Environment Variables

Some live tests need values that are specific to your SAP system. They have no defaults; tests that need an unset variable are skipped.

| Variable                     | Used by                                         | Meaning                                                                         |
| ---------------------------- | ----------------------------------------------- | ------------------------------------------------------------------------------- |
| `SAP_TEST_TRANSPORT`         | abapGit pull/e2e tests                          | A modifiable workbench transport request on which the test user has a task      |
| `SAP_TEST_TRANSPORT_NO_TASK` | `test_abapgit_pull_transport_without_user_task` | A modifiable workbench transport request on which the test user has **no** task |
| `ABAPGIT_PAT`                | abapGit tests with a private repository         | GitHub token that can read the private test repository (tests skip without it)  |

The SE09 and ST22 live tests use the user returned by `sap_login`, so no user variable is needed.

## Client Side

- **Chrome browser** installed
- **VPN** connected (if the SAP system is on an internal network)
- **uv** and the project environment (see [CONTRIBUTING.md](../CONTRIBUTING.md#development-setup))

### Start Chrome with Remote Debugging

The tests connect to a running Chrome through the Chrome DevTools Protocol (CDP, `BROWSER_MODE=connect`, the default). Start Chrome with a separate profile directory (without `--user-data-dir`, Chrome joins an existing instance and ignores the debugging flag):

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\temp\chrome-debug" --ignore-certificate-errors
```

On macOS or Linux use the Chrome binary of your system with the same flags (for example `--user-data-dir=/tmp/chrome-debug`). Verify it is working:

```powershell
Invoke-WebRequest -Uri 'http://localhost:9222/json/version' -UseBasicParsing
```

On Windows, the server auto-launches Chrome with these flags when none is reachable (set `CHROME_PATH` if it cannot find Chrome, see the [README](../README.md#environment-variables-server-specific)). On macOS and Linux you must start Chrome yourself.

### Credentials Configuration

SAP credentials are configured in `~/.config/sap-mcp/systems.json` (see [sap-mcp-config](https://github.com/Hochfrequenz/sap-mcp-config)). The `host`, user, password, client and language come from there. A system entry for the tests looks like this:

```json
{
    "default_system": "dev",
    "systems": {
        "dev": {
            "host": "https://your-sap-server:44300",
            "client": "100",
            "user": "your_username",
            "password": "your_password",
            "language": "DE"
        }
    }
}
```

`.env` (in the repository root, read by pytest and by the server) only needs the test-specific settings:

```env
SAP_LANGUAGE=DE
BROWSER_MODE=connect
CDP_URL=http://localhost:9222
```

`SAP_LANGUAGE` is read by the tests only (they pick their expected UI texts and snapshot suffix from it); the language the server logs on with comes from the system's `language` in `systems.json`. Keep both the same. Set `SAP_URL` only if the WebGUI URL differs from `{host}/sap/bc/gui/sap/its/webgui`. To run against another file, point `SAP_CONFIG_FILE` at it.

## Running the Tests

Every test that requests the `sap_mcp_client` fixture is marked `integration` automatically (see `unittests/conftest.py`). Use `-m integration` to run only live tests and `-m "not integration"` to exclude them. Live tests skip when SAP credentials are not configured.

```bash
# All live tests
uv run --group tests python -m pytest unittests/webgui/ -m integration -v

# One module
uv run --group tests python -m pytest unittests/webgui/test_se16_integration.py -v

# Offline selector tests (no SAP or Chrome needed, uses HTML snapshots)
uv run --group tests python -m pytest unittests/webgui/test_selectors.py -v
```

All live tests share one Chrome through CDP and one SAP user. Run them one process at a time.

### HTML Snapshots

WebGUI unit tests validate CSS selectors against captured HTML snapshots stored in `unittests/testdata/html_snapshots/`. These are system-specific: transport numbers, user names, and other data in the snapshots come from the system they were captured on. If you switch to a new SAP system, re-capture the snapshots with `scripts/recapture-snapshots.ps1` (it runs the integration tests with `SAP_LANGUAGE=DE` and `SAP_LANGUAGE=EN`).

## Troubleshooting

| Problem                          | Solution                                                                   |
| -------------------------------- | -------------------------------------------------------------------------- |
| Chrome connection errors         | Ensure `--remote-debugging-port=9222` and `--user-data-dir` flags are set  |
| "Cannot connect to CDP"          | Check Chrome is running, verify with `http://localhost:9222/json/version`  |
| SAP login fails                  | Check the system's `host` is reachable in the browser, verify credentials  |
| OK-Code field not visible        | Enable in SAP Web GUI settings (gear icon → Settings → Show OK-Code Field) |
| Tools timeout                    | SAP Web GUI can be slow; check the Chrome window for SAP's response        |
| SE09 tests fail, no transports   | Create the test objects above (this generates transports automatically)    |
| Snapshot tests fail after system | Re-capture HTML snapshots: run the integration tests, then the unit tests  |
