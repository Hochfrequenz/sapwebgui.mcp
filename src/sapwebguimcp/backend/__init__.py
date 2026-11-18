"""Backend abstraction layer for SAP UI interaction."""

from sapwebguimcp.backend.manager import (
    close_backend,
    get_backend,
    get_backend_manager,
    get_webgui_backend,
    reset_backend_manager,
)
from sapwebguimcp.backend.webgui.types import AriaSnapshot
from sapwebguimcp.models.base import CheckActivateResult

__all__ = [
    "AriaSnapshot",
    "CheckActivateResult",
    "close_backend",
    "get_backend",
    "get_backend_manager",
    "get_webgui_backend",
    "reset_backend_manager",
]
