"""
MCP Server for SAP Web GUI browser automation.

This module provides the main entry point for the MCP server using FastMCP.
Tools are organized in separate modules under sapwebguimcp.tools.
"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from dotenv import dotenv_values
from fastmcp import FastMCP
from fastmcp.apps.choice import Choice
from fastmcp.server.middleware.logging import LoggingMiddleware

from sapwebguimcp.backend.manager import close_backend
from sapwebguimcp.logging_config import configure_logging
from sapwebguimcp.middleware import ToolCallLoggingMiddleware
from sapwebguimcp.middleware.logging import masked_payload_serializer
from sapwebguimcp.models.config import get_settings, try_get_sap_config
from sapwebguimcp.prompts import register_prompts
from sapwebguimcp.resources import (
    register_feedback_resources,
    register_intent_resources,
)
from sapwebguimcp.tools import (
    register_abapgit_tools,
    register_browser_tools,
    register_catalog_tools,
    register_class_tools,
    register_feedback_tools,
    register_fm_tools,
    register_intent_tools,
    register_quick_report_tools,
    register_sap_tools,
    register_se09_tools,
    register_se11_tools,
    register_se16_tools,
    register_se24_edit_tools,
    register_se24_tools,
    register_se37_edit_tools,
    register_se37_tools,
    register_se38_edit_tools,
    register_se93_tools,
    register_slg1_tools,
    register_sm30_tools,
    register_sm37_tools,
    register_spro_tools,
    register_st22_tools,
    register_table_tools,
)
from sapwebguimcp.tools.abapgit_tools import validate_github_pat

__all__ = ["main", "mcp"]

# Get settings (needed for logging configuration)
_settings = get_settings()

# Configure logging
configure_logging(
    log_format=_settings.log_format,
    log_level=_settings.log_level,
)
logger = logging.getLogger(__name__)

# Note: GitHub issue creation is handled directly in log_feedback tool (async)


async def _check_cdp_available(cdp_url: str) -> bool:
    """Check Chrome CDP availability. If not reachable, log that auto-launch will be attempted."""
    try:
        async with httpx.AsyncClient() as client:
            await client.get(f"{cdp_url}/json/version", timeout=2.0)
        logger.info("[OK] Chrome CDP reachable at %s", cdp_url)
        return True
    except (httpx.ConnectError, httpx.TimeoutException, OSError):
        logger.info(
            "Chrome not detected at %s. Will attempt auto-launch when browser is needed.",
            cdp_url,
        )
        return False


_DESKTOP_MOVED_NOTICE = (
    "NOTICE: SAP GUI for Windows (desktop) support moved to a separate project, sapgui.mcp "
    "(https://github.com/Hochfrequenz/sapgui.mcp). This server only drives SAP WebGUI in a browser and "
    "ignores BACKEND_TYPE. Use sapgui.mcp for SAP GUI for Windows automation."
)


def _env_files() -> tuple[str, ...]:
    """The .env files the settings load (``SapGuiSettings.model_config['env_file']``)."""
    return (".env",)


def _legacy_setting_values() -> dict[str, str]:
    """The settings from the .env files the settings load, overridden by the process environment (keys upper-cased)."""
    values: dict[str, str] = {}
    for env_file in _env_files():
        try:
            loaded = dotenv_values(env_file)
        except OSError:
            continue
        values.update({k.upper(): v for k, v in loaded.items() if v is not None})
    values.update({k.upper(): v for k, v in os.environ.items()})
    return values


def _legacy_desktop_setting() -> bool:
    """Whether BACKEND_TYPE=desktop is set, in the environment or a .env file (key and value case-insensitive)."""
    return _legacy_setting_values().get("BACKEND_TYPE", "").strip().lower() == "desktop"


def _warn_legacy_desktop_setting() -> bool:
    """Log a warning when BACKEND_TYPE=desktop is set. Never fails; returns whether it is set."""
    found = _legacy_desktop_setting()
    if found:
        logger.warning(
            "Legacy setting BACKEND_TYPE=desktop detected. SAP GUI for Windows support moved to the separate "
            "project sapgui.mcp (https://github.com/Hochfrequenz/sapgui.mcp); this server uses SAP WebGUI only "
            "and ignores it."
        )
    return found


@asynccontextmanager
async def app_lifespan(_server: FastMCP) -> AsyncIterator[None]:
    """
    Manage application lifecycle.

    This context manager handles cleanup of backend resources on shutdown.
    The backend is initialized lazily on first tool call via get_backend().
    """
    try:
        from _sapwebguimcp_version import version as _server_version  # pylint: disable=import-outside-toplevel
    except (ImportError, SyntaxError):
        _server_version = "unknown"
    logger.info("[STARTING] SAP MCP Server v%s initializing...", _server_version)
    cdp_ok = await _check_cdp_available(_settings.cdp_url)
    if cdp_ok:
        logger.info("[READY] Server started successfully. Waiting for MCP client connection on stdio.")
    else:
        logger.info("[READY] Server started. Chrome not detected yet — will auto-launch when browser is needed.")

    # Validate GitHub PAT if configured (non-blocking, warns only)
    _current_settings = get_settings()
    effective_pat = _current_settings.abapgit_pat or _current_settings.github_pat
    _pat_source = "ABAPGIT_PAT" if _current_settings.abapgit_pat else "GITHUB_PAT"
    if effective_pat:
        pat_valid, pat_msg = await validate_github_pat(effective_pat)
        if pat_valid:
            logger.info("[OK] %s validated (user: %s)", _pat_source, pat_msg)
        else:
            logger.warning(
                "[ACTION REQUIRED] %s is invalid: %s. "
                "abapGit pulls will fail. Regenerate at https://github.com/settings/tokens",
                _pat_source,
                pat_msg,
            )

    try:
        yield
    finally:
        logger.info("[STOPPING] Cleaning up backend resources...")
        await close_backend()
        logger.info("[STOPPED] Server shutdown complete.")


# Instructions for the LLM about this MCP server
_WEBGUI_INSTRUCTIONS = """
SAP Web GUI automation server. Controls SAP through a Chrome browser with remote debugging enabled.
This server only supports SAP Web GUI in a browser.

BROWSER SETUP:
On Windows, Chrome is auto-launched with debugging flags when not already running.
On Windows, if Chrome cannot be found automatically, set CHROME_PATH (MCP client env block).
CHROME_PATH has no effect on macOS and Linux.
On macOS and Linux (and in Docker) the user must start Chrome first with --remote-debugging-port=9222.
The user may also pre-launch Chrome manually on Windows.

IMPORTANT: Do NOT attempt to install Chrome or any browser.

PREREQUISITES:
- Chrome installed (Windows: auto-detected, or CHROME_PATH; macOS/Linux: started by the user)
- VPN connected (if SAP system is on internal network)
- CDP proxy running (only when this server runs in Docker)

IF CONNECTION FAILS:
Do NOT try to install browsers. Instead, ask the user to verify:
1. "Is Chrome running with --remote-debugging-port=9222?"
   (Windows: the server starts it, set CHROME_PATH if it is not found; macOS/Linux: the user must start it)
2. "Is your VPN connected?" (for internal SAP systems)
3. "Is the CDP proxy running?" (Docker setups only: docker compose up -d)

COMMON ERROR CAUSES:
- "Chrome not found" / "Chrome konnte nicht ... gefunden werden": Windows only: set CHROME_PATH
- "SAP URL not reachable": VPN not connected
- Login fails: Check user/password/client in ~/.config/sap-mcp/systems.json

WORKFLOW:
1. Call sap_login first to open SAP and authenticate
2. Use sap_transaction to navigate to transactions (e.g., VA01, SE16, BP)
3. Use browser_snapshot to see current screen state
4. Use browser_fill/browser_click for interactions
5. Prefer SAP-specific tools (sap_fill_form, sap_click_button) over browser_* tools when available

ESCAPE HATCHES (when SAP-specific tools are insufficient):
- browser_snapshot: See current DOM/ARIA tree
- browser_evaluate: Execute arbitrary JavaScript
- browser_click / browser_fill: Interact with elements by CSS selector
- browser_navigate: Navigate to a URL (e.g., SAP Help Portal)
"""

_CROSS_SERVER_GUIDANCE = """
WHEN TO USE THIS SERVER vs sap-adt MCP:
If sap-adt (SAP ADT MCP) tools are available, prefer them for:
- Reading/writing ABAP source code (get_source, patch_source, set_source_from_file)
- Creating ABAP objects (create_object: PROG, CLAS, INTF, FUGR, MSAG, DDLS, TABL, DTEL, DOMA)
- Transport management (get_transport_requests, create_transport, release_transport on S4)
- Activation, syntax checks, ATC checks, unit tests
- Code completion, pretty printing, refactoring
- Debugging (breakpoints, stepping, variable inspection; this server has no debugger tools)
- DDIC lookups (get_object_info, get_ddic_info)

Use THIS server (sap-webgui) for:
- Customizing transactions (SPRO, SM30, SM34)
- Transport release on ECC (SE09 — ADT release may silently fail on ECC)
- Complex GUI interactions (popups, tabs, grids)
- Transactions without ADT endpoints (SE21 on ECC, SM37, SLG1, ST22, SQVI)
- Visual verification of screen state
- abapGit operations (sap_abapgit_pull, sap_abapgit_list_repos)

TRANSACTION SELECTION:
- Prefer dedicated transactions (SE38, SE24, SE37, SE21) over SE80
- SE80 has a complex split-screen layout that tools struggle to parse
"""


def _build_instructions() -> str:
    base = _CROSS_SERVER_GUIDANCE + _WEBGUI_INSTRUCTIONS
    if _warn_legacy_desktop_setting():
        base += "\n" + _DESKTOP_MOVED_NOTICE + "\n"
    sap_cfg, config_error = try_get_sap_config()
    if config_error:  # invalid config: don't crash startup, but say why
        logger.error("SAP config file could not be loaded, no systems listed: %s", config_error)
        return (
            base
            + "\nCONFIGURATION ERROR: the SAP config file (SAP_CONFIG_FILE / systems.json) could not be loaded, "
            + "no systems are available until it is fixed:\n"
            + f"{config_error}\n"
            + "The server must be restarted after fixing the file for these instructions to update; "
            + "sap_list_connections reports the live state.\n"
        )
    if sap_cfg is None:  # no config file: nothing to list, tools report it when they need it
        return base
    keys = list(sap_cfg.systems.keys())
    default = sap_cfg.default_system
    return (
        base + f"\nAVAILABLE SYSTEMS (from systems.json):\n"
        f"Default: {default!r}\n"
        f"All system keys: {keys}\n"
        f"When multiple systems are configured, use the choose tool to let the user "
        f"pick a system before calling sap_login(). "
        f"Pass the selected key as system_key to sap_login().\n"
    )


SERVER_INSTRUCTIONS = _build_instructions()

# Create the FastMCP server instance with strict input validation
_SERVER_NAME = "sap-webgui-mcp"
mcp = FastMCP(
    _SERVER_NAME,
    instructions=SERVER_INSTRUCTIONS,
    lifespan=app_lifespan,
    strict_input_validation=True,
)

# Add logging middleware for tool call sequence analysis
mcp.add_middleware(ToolCallLoggingMiddleware())

# Add Choice provider so the LLM can present system selection UI to the user
mcp.add_provider(Choice())

# Add FastMCP built-in logging with payload visibility
mcp.add_middleware(
    LoggingMiddleware(include_payloads=True, max_payload_length=1000, payload_serializer=masked_payload_serializer)
)

# Register tools (WebGUI only)

# SAP tools + transaction-specific tools
register_sap_tools(mcp)
register_se11_tools(mcp)
register_se16_tools(mcp)
register_se24_tools(mcp)
register_se37_tools(mcp)
register_se09_tools(mcp)
register_se93_tools(mcp)
register_slg1_tools(mcp)
register_sm30_tools(mcp)
register_sm37_tools(mcp)
register_spro_tools(mcp)
register_st22_tools(mcp)
register_catalog_tools(mcp)
register_table_tools(mcp)
register_fm_tools(mcp)
register_class_tools(mcp)
register_se24_edit_tools(mcp)
register_se38_edit_tools(mcp)

# Logging, abapgit
register_intent_tools(mcp)
register_feedback_tools(mcp)
register_abapgit_tools(mcp)

# Browser escape hatches, SE37 editor, quick report
register_browser_tools(mcp)
register_se37_edit_tools(mcp)
register_quick_report_tools(mcp)

# Register prompts
register_prompts(mcp)

# Register resources
register_intent_resources(mcp)
register_feedback_resources(mcp)


def main() -> None:
    """Main entry point for the MCP server."""
    try:
        # stdio only: one process serves one client, which sapwebguimcp.mcp_session relies on.
        mcp.run(transport="stdio", show_banner=False)
    except Exception:
        logger.critical("[CRASHED] Server crashed with unhandled exception", exc_info=True)
        raise
    finally:
        logging.shutdown()


if __name__ == "__main__":
    main()
