"""Tests for BackendManager."""

import asyncio
from unittest.mock import AsyncMock, patch

from sapwebguimcp.backend.manager import (
    BackendManager,
    close_backend,
    get_backend_manager,
    reset_backend_manager,
)


def test_get_backend_manager_is_singleton() -> None:
    """get_backend_manager should lazily create one shared manager."""
    reset_backend_manager()
    manager = get_backend_manager()
    assert get_backend_manager() is manager
    reset_backend_manager()


def test_close_backend_no_manager() -> None:
    """close_backend should be a no-op when no manager exists."""
    reset_backend_manager()
    asyncio.run(close_backend())  # Should not raise
    reset_backend_manager()


def test_backend_manager_close_clears_caches() -> None:
    """BackendManager.close() should clear internal caches and call close_browser_manager."""
    manager = BackendManager()
    # Simulate cached state
    manager._backends["s1"] = "fake_backend"  # type: ignore[assignment]
    manager._page_ids["s1"] = 12345

    with patch(
        "sapwebguimcp.backend.manager.close_browser_manager",
        new_callable=AsyncMock,
    ) as mock_close:
        asyncio.run(manager.close())
        mock_close.assert_called_once()

    assert manager._backends == {}
    assert manager._page_ids == {}
