"""Unit tests for sap_list_connections tool."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

_PATCH_GET_BACKEND = "sapguimcp.tools.sap_list_connections_impl.get_backend"
_PATCH_GET_SAP_CONFIG = "sapguimcp.models.config.get_sap_config"


class TestSapListConnectionsTool:
    """sap_list_connections returns available SAP Logon entries."""

    @pytest.mark.anyio
    async def test_returns_connection_list(self) -> None:
        """Tool calls backend.list_connections and returns results."""
        from sapguimcp.tools.sap_list_connections_impl import sap_list_connections_impl

        backend = AsyncMock()
        backend.list_connections.return_value = [
            {"name": "sysA", "type": "SAPGUI", "systemid": "sysA", "server": "192.0.2.10:3200", "client": ""},
            {
                "name": "sysB",
                "type": "SAPGUI",
                "systemid": "sysB",
                "server": "sap-host-b.example.com:3200",
                "client": "",
            },
        ]

        with patch(_PATCH_GET_BACKEND, new=AsyncMock(return_value=backend)):
            result = await sap_list_connections_impl()

        assert result.success is True
        assert len(result.connections) == 2
        assert result.connections[0]["name"] == "sysA"


def _make_sap_config():
    """Create a mock SapMcpConfig with two systems."""
    from sap_mcp_config import Config, SAPSystem

    return Config(
        default_system="sysA",
        systems={
            "sysA": SAPSystem(
                connection_name="DEV S/4HANA",
                host="https://sap-host-a.example.com",
                client="100",
                user="testuser",
                password=SecretStr("secret1"),
                language="DE",
            ),
            "sysB": SAPSystem(
                connection_name="DEV R3",
                host="https://sap-host-c.example.com",
                client="100",
                user="testuser",
                password=SecretStr("secret2"),
                language="DE",
            ),
        },
    )


class TestConfiguredSystems:
    """configured_systems exposes systems.json entries without passwords."""

    def test_get_configured_systems_returns_safe_fields(self) -> None:
        from sapguimcp.tools.sap_list_connections_impl import _get_configured_systems

        with patch(_PATCH_GET_SAP_CONFIG, return_value=_make_sap_config()):
            systems, error = _get_configured_systems()

        assert error is None
        assert len(systems) == 2
        s4 = next(s for s in systems if s["key"] == "sysA")
        assert s4["sap_logon_entry"] == "DEV S/4HANA"
        assert s4["host"] == "https://sap-host-a.example.com"
        assert s4["client"] == "100"
        assert s4["language"] == "DE"
        assert "password" not in s4
        assert "user" not in s4

    def test_get_configured_systems_no_config(self) -> None:
        from sapguimcp.tools.sap_list_connections_impl import _get_configured_systems

        with patch(_PATCH_GET_SAP_CONFIG, side_effect=FileNotFoundError):
            systems, error = _get_configured_systems()

        assert systems == []
        assert error is None  # no config file is a legitimate setup, not an error

    def test_get_configured_systems_invalid_config_reports_error(self) -> None:
        from sapguimcp.tools.sap_list_connections_impl import _get_configured_systems

        message = 'system "dev": language must be one of "DE", "EN", got "IT"'
        with patch(_PATCH_GET_SAP_CONFIG, side_effect=ValueError(message)):
            systems, error = _get_configured_systems()

        assert systems == []
        assert error == message

    @pytest.mark.anyio
    async def test_tool_reports_invalid_config_instead_of_silent_empty_list(self) -> None:
        from sapguimcp.tools.sap_list_connections_impl import sap_list_connections_impl

        message = 'system "dev": language must be one of "DE", "EN", got "IT"'
        with (
            patch(_PATCH_GET_BACKEND, new=AsyncMock(side_effect=RuntimeError("no backend"))),
            patch(_PATCH_GET_SAP_CONFIG, side_effect=ValueError(message)),
        ):
            result = await sap_list_connections_impl()

        assert result.configured_systems == []
        assert result.config_error is not None
        assert "language must be one of" in result.config_error

    @pytest.mark.anyio
    async def test_tool_includes_configured_systems(self) -> None:
        from sapguimcp.tools.sap_list_connections_impl import sap_list_connections_impl

        backend = AsyncMock()
        backend.list_connections.return_value = [
            {"name": "sysA", "type": "SAPGUI", "systemid": "sysA"},
        ]

        with (
            patch(_PATCH_GET_BACKEND, new=AsyncMock(return_value=backend)),
            patch(_PATCH_GET_SAP_CONFIG, return_value=_make_sap_config()),
        ):
            result = await sap_list_connections_impl()

        assert result.success is True
        assert len(result.connections) == 1
        assert len(result.configured_systems) == 2
        keys = [s["key"] for s in result.configured_systems]
        assert "sysA" in keys
        assert "sysB" in keys

    @pytest.mark.anyio
    async def test_tool_returns_systems_even_when_backend_fails(self) -> None:
        from sapguimcp.tools.sap_list_connections_impl import sap_list_connections_impl

        with (
            patch(_PATCH_GET_BACKEND, new=AsyncMock(side_effect=RuntimeError("no backend"))),
            patch(_PATCH_GET_SAP_CONFIG, return_value=_make_sap_config()),
        ):
            result = await sap_list_connections_impl()

        assert result.success is True
        assert result.connections == []
        assert len(result.configured_systems) == 2
