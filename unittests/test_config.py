"""Tests for the configuration module."""

import os
from unittest.mock import patch

from sapguimcp.models.config import (
    BrowserMode,
    BrowserType,
    SapGuiSettings,
    get_settings,
)


class TestSapGuiSettings:
    """Tests for SapGuiSettings."""

    def test_default_values(self) -> None:
        """Test that default values are set correctly."""
        with patch.dict(os.environ, {}, clear=True):
            settings = SapGuiSettings(_env_file=None)

        assert settings.sap_url == ""
        assert settings.browser_mode == BrowserMode.CONNECT
        assert settings.browser_type == BrowserType.CHROMIUM
        assert settings.browser_headless is False
        assert settings.cdp_url == "http://localhost:9222"
        assert settings.script_roots == ""

    def test_env_variable_loading(self) -> None:
        """Test that environment variables are loaded correctly."""
        env_vars = {
            "SAP_URL": "https://sap.example.com/webgui",
            "BROWSER_MODE": "connect",
            "BROWSER_TYPE": "firefox",
            "BROWSER_HEADLESS": "true",
            "CDP_URL": "http://localhost:9333",
            "SCRIPT_ROOTS": "/opt/scripts:/home/scripts",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            settings = SapGuiSettings(_env_file=None)

        assert settings.sap_url == "https://sap.example.com/webgui"
        assert settings.browser_mode == BrowserMode.CONNECT
        assert settings.browser_type == BrowserType.FIREFOX
        assert settings.browser_headless is True
        assert settings.cdp_url == "http://localhost:9333"
        assert settings.script_roots == "/opt/scripts:/home/scripts"

    def test_validate_for_browser_connect_mode_missing_cdp(self) -> None:
        """Test validation when in connect mode without CDP URL."""
        env_vars = {
            "BROWSER_MODE": "connect",
            "CDP_URL": "",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            settings = SapGuiSettings(_env_file=None)

        errors = settings.validate_for_browser()
        assert len(errors) == 1
        assert "CDP_URL is required" in errors[0]

    def test_validate_for_browser_launch_mode(self) -> None:
        """Test validation passes in launch mode."""
        with patch.dict(os.environ, {"BROWSER_MODE": "launch"}, clear=True):
            settings = SapGuiSettings(_env_file=None)

        errors = settings.validate_for_browser()
        assert len(errors) == 0


class TestGetSettings:
    """Tests for the get_settings function."""

    def test_returns_settings_instance(self) -> None:
        """Test that get_settings returns a SapGuiSettings instance."""
        import sapguimcp.models.config

        sapguimcp.models.config._settings = None

        settings = get_settings()
        assert isinstance(settings, SapGuiSettings)

    def test_returns_same_instance(self) -> None:
        """Test that get_settings returns the same instance on subsequent calls."""
        import sapguimcp.models.config

        sapguimcp.models.config._settings = None

        settings1 = get_settings()
        settings2 = get_settings()
        assert settings1 is settings2
