# Contributing to SAP Web GUI MCP Server

Thank you for contributing to this project! This guide covers development setup, testing, and coding standards.

This project looks for a maintainer and may not receive updates. It drives SAP Web GUI in a browser. For SAP GUI for Windows, use [sapgui.mcp](https://github.com/Hochfrequenz/sapgui.mcp).

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full architecture overview — layers, request flow diagrams, file organization, and how to add new transaction tools.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/Hochfrequenz/sapwebgui.mcp.git
cd sapwebgui.mcp

# Install uv first: https://docs.astral.sh/uv/getting-started/installation/
# Then create the development environment
uv sync --group dev

# Activate the environment
source .venv/bin/activate  # Linux/macOS
# or
.venv\Scripts\activate  # Windows

# Install the Playwright Chromium used by the browser unit tests
# (the server itself connects to your own Chrome, see the README)
uv run playwright install chromium
```

`uv sync --group dev` installs everything needed to run the unit tests (`dev` includes the `tests` group and the runtime dependencies such as `fastmcp`). If a bare `pytest` or `import mcp` fails with a missing module, you are most likely in a stale or different virtual environment: run commands through `uv run ...` (e.g. `uv run pytest --version`) instead of relying on an activated older venv.

### SAP Test System Setup

To run integration tests, you need a configured SAP system. See **[docs/SAP_TEST_PREREQUISITES.md](docs/SAP_TEST_PREREQUISITES.md)** for:

- Chrome with remote debugging and the `systems.json` credentials file
- Required test objects (report, class) and abapGit test repositories
- `.env` file configuration

## Running Tests

This project uses [uv](https://docs.astral.sh/uv/) to run all tests and checks. The test suite includes:

- **Unit tests**: Offline tests using HTML snapshots and mocks (no SAP required)
- **Integration tests**: Tests against a real SAP Web GUI in Chrome (marked `integration`, auto-skipped without SAP credentials)

### Commands

```bash
# Run all tests (integration tests auto-skip if SAP not accessible)
uv run --group tests python -m pytest

# Run only unit tests (fast, no SAP needed)
uv run --group tests python -m pytest unittests/ -m "not integration"

# Run only SAP integration tests (requires SAP access)
uv run --group tests python -m pytest unittests/ -m integration
```

SAP credentials and the logon language of the system come from `~/.config/sap-mcp/systems.json`. The integration tests also read `SAP_LANGUAGE` (`DE`, `EN` or `IT`) from your `.env` file to pick their expected UI texts.

**Other checks:**

```bash
uv run --group coverage coverage run -m pytest  # Run tests with coverage report
uv run --group linting ruff check .             # Run ruff (lint)
uv run --group linting ruff format --check .     # Check formatting
uv run --group linting ruff check --select I .   # Check import order
uv run --group type_check mypy --show-error-codes src/sapwebguimcp --strict  # Run mypy type checking
uv run --group spell_check codespell --ignore-words=domain-specific-terms.txt src  # Run codespell
```

### Running Tests in PyCharm

You can run tests directly in PyCharm. Settings are loaded from your `.env` file automatically.

1. **Unit tests**: Right-click `unittests/webgui/test_selectors.py` → Run
2. **Integration tests**: Right-click any `unittests/webgui/test_*_integration.py` file → Run

To change the test language, edit `SAP_LANGUAGE` in your `.env` file (and use a system with that `language` in `systems.json`).

**uv vs PyCharm**: uv creates an isolated virtualenv (good for CI), PyCharm uses your current interpreter (faster for development).

### HTML Snapshot Testing

We use HTML snapshots captured from real SAP Web GUI sessions to test CSS selectors offline. This approach:

1. **Captures real HTML** during integration tests (when SAP is available)
2. **Validates selectors** against snapshots in fast unit tests (no SAP needed)
3. **Supports multiple languages** (snapshots named `*_en.html`, `*_de.html`)

To capture new snapshots, set `SAP_LANGUAGE` in your `.env` file and run integration tests (or run `scripts/recapture-snapshots.ps1`, which does it for DE and EN):

```bash
uv run --group tests python -m pytest unittests/ -m integration   # Captures snapshots in configured language
uv run --group tests python -m pytest unittests/ -m "not integration"  # Run offline selector tests (no SAP needed)
```

Snapshots are stored in `unittests/testdata/html_snapshots/`.

#### Why Not Syrupy?

We considered [syrupy](https://github.com/tophat/syrupy) (a pytest snapshot testing library) but chose a simpler approach because:

1. **SAP HTML is huge** (~300KB per page) - syrupy's diff output would be unreadable
2. **We don't compare full HTML** - we only validate that specific selectors find elements
3. **Selector validation is the goal** - not detecting HTML changes
4. **BeautifulSoup is sufficient** - we parse HTML and test CSS selectors, no need for snapshot diffing
5. **Multi-language support** - we capture EN/DE variants; syrupy would create separate snapshot dirs

Our approach: capture HTML once, then write focused assertions about selector behavior. If SAP's HTML structure changes, the selector tests fail with clear messages about which selector broke.

### WebGUI Integration Tests

WebGUI integration tests run against SAP Web GUI in a browser. They:

- Require SAP credentials in environment
- Are slow (~10-30s each)
- Should capture HTML snapshots for debugging

```python
@pytest.mark.anyio
async def test_my_feature(sap_mcp_client: ClientSession) -> None:
    await sap_mcp_client.call_tool("sap_login", {})
    # ... test logic
    await capture_html_snapshot(sap_mcp_client, "my_feature_result")
```

### Unit Tests

Unit tests use HTML snapshots and mocks. No SAP connection needed.

```python
# HTML snapshot test of a parser
def test_my_parser():
    html = load_snapshot("bp_person_form_de.html")
    result = parse_something(html)
    assert result == expected
```

Every test that requests the `sap_mcp_client` fixture is marked `integration` automatically (see
`unittests/conftest.py`), so `-m "not integration"` excludes exactly the live tests.

See [docs/SAP_TEST_PREREQUISITES.md](docs/SAP_TEST_PREREQUISITES.md) for the system setup the live tests need.

### Executable and Docker Image

CI builds a standalone executable (PyInstaller) and a Docker image; see `.github/workflows/build_executable.yml`,
`.github/workflows/python-publish.yml` and the `Dockerfile`. To try them locally:

```bash
# Windows executable (writes dist/sapwebgui_mcp_windows.exe), then the smoke test CI runs
uv run --locked --group build_executable pyinstaller --noconfirm sapwebgui_mcp_windows.spec
uv run --no-project python scripts/smoke_test_exe.py dist/sapwebgui_mcp_windows.exe

# Docker image
docker build -t sapwebgui-mcp:local .
```

## Code Style

This project uses:

- [ruff](https://docs.astral.sh/ruff/) for linting, import sorting and code formatting (replaces black, isort and pylint) — when adding per-file ignores keep the human-readable rule **name** as a trailing comment (`# too-many-arguments`), not just the code
- [mypy](https://mypy.readthedocs.io/) for type checking
- [codespell](https://github.com/codespell-project/codespell) for spell checking

### Python

The `dev` and `linting` dependency groups install ruff.

```bash
uv run --group linting ruff format .   # Format code
uv run --group linting ruff check --fix .   # Lint and auto-fix (incl. import sorting)
```

Linting and type checking:

```bash
uv run --group linting ruff check .
uv run --group type_check mypy --show-error-codes src/sapwebguimcp --strict
```

### JavaScript and Markdown

Use Prettier for formatting (run `npm ci` once to install it):

```bash
npm run format
```

### SAP UI Texts and Languages

SAP screen texts differ per logon language, so they live only in the language packs under
`src/sapwebguimcp/lang/`. Never write a button label, title, status text or column header as a literal
in tool, parser or JS code: read it from `lang.current()` (see
[`ARCHITECTURE.md`](ARCHITECTURE.md#sap-ui-texts-and-language-packs) and the
[design spec](docs/superpowers/specs/2026-11-10-language-packs-design.md)).

`unittests/test_no_ui_literals.py` enforces this. If it flags a literal, move the text into the
packs (plus a `SOURCES` entry in `lang/sources.py`), or, when the literal is code or the server's
own message, add `# lang-ok: <reason>` on the flagged line (`// lang-ok: <reason>` in JS). Never add
to `unittests/lang_baseline.json`; it is empty.

To add a new login language: create `lang/<xx>.py` modelled on `en.py`, register it in
`lang/__init__.py`, fill the test pack in `unittests/testdata/lang_test.py`, verify it with
`uv run python scripts/harvest_lang_texts.py <XX> --verify`, and run
`uv run --group tests pytest unittests/lang unittests/test_no_ui_literals.py` (the pseudo-locale test
included). The full guide, with the pitfalls found while migrating DE and EN, is
[`src/sapwebguimcp/lang/ADDING_A_LANGUAGE.md`](src/sapwebguimcp/lang/ADDING_A_LANGUAGE.md).

## MCP Tool Guidelines

### Tool and Parameter Descriptions (Important!)

FastMCP uses **two sources** to generate the MCP tool schema:

1. **Tool description** → from `@mcp.tool(description=...)` decorator
2. **Parameter descriptions** → from the **Args section in the docstring**

Both are sent to the AI client. Without the Args section, the LLM doesn't know what parameters exist!

```python
# CORRECT - description in decorator, Args in docstring
@mcp.tool(
    description=(
        "Discover clickable buttons on the current SAP screen. "
        "Prefer keyboard shortcuts (sap_press_key) when available — "
        "they're faster and more reliable. "
        "For input fields use sap_discover_fields instead."
    )
)
async def sap_discover_buttons(session: str | None = None) -> DiscoveredButtons:
    """Discover all clickable buttons on the current SAP screen.

    Args:
        session: Session ID (e.g., "s1", "s2"). None uses primary session.
    """
    ...

# WRONG - missing Args section (parameter won't have description in schema)
@mcp.tool(description="Discover buttons")
async def sap_discover_buttons(session: str | None = None) -> DiscoveredButtons:
    """Discover all clickable buttons on the current SAP screen."""
    ...
```

**Key points:**

- Put **when/why to use the tool** in the `description` decorator
- Put **what each parameter means** in the docstring Args section
- FastMCP parses the Args section to generate parameter descriptions in the MCP schema

### JavaScript Files

- Place JavaScript in `src/sapwebguimcp/backend/webgui/js/`
- Use IIFE pattern: `() => { ... }`
- Load with `load_js("filename.js")` from `sapwebguimcp.backend.webgui.js_helpers` in Python
- Document SAP-specific quirks in comments

### Pydantic Models and DTOs

- Place in `src/sapwebguimcp/models/`
- Use `Field(description=...)` for all fields
- Export from `__init__.py`

## Python Specific Guidelines

Use strict typing:

- Pydantic models for data structures instead of plain dicts, tuples or dataclasses
    - Pydantic model fields should have descriptions
- Proper type hints for function parameters and return types

### MCP

Read the docs of [FastMCP](https://gofastmcp.com/servers/server) before you google or guess.

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/).
In the long commit message include what we learned (about SAP, about Playwright, about MCP usage etc.).
Also include what assumptions we made and which prior assumptions turned out to be wrong.
Be honest.

### No Force Push

Do not force push unless absolutely necessary and discussed with the team.

### No Amend

In the end, one pull request should contain one logical change.
We'll squash merge PRs when they're ready.
So it's ok to have commits that are not perfect.
You don't need to put any effort in rebases, amends or similar.

## Pull Requests

1. Create a feature branch: `feat/my-feature` or `fix/my-bug`
2. Write tests for new functionality
3. Ensure all tests pass: `uv run --group tests python -m pytest unittests/ -m "not integration"`
4. Ensure linting passes: `uv run --group linting ruff check .`, `uv run --group type_check mypy --show-error-codes src/sapwebguimcp --strict`
5. Create PR with clear description

## Extending the Server

### Adding New Tools

See [src/sapwebguimcp/tools/README.md](src/sapwebguimcp/tools/README.md) for detailed instructions on creating new tools.

### Adding New Models

See [src/sapwebguimcp/models/README.md](src/sapwebguimcp/models/README.md) for information about the data models.

### Creating Skills

See [src/sapwebguimcp/skills/README.md](src/sapwebguimcp/skills/README.md) for how to create reusable workflows.
