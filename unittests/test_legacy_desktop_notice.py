"""Tests for the notice and warning shown to users who still set BACKEND_TYPE=desktop."""

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from sapguimcp import server


@pytest.fixture(autouse=True)
def _no_legacy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BACKEND_TYPE", raising=False)
    # A developer's own .env must not leak into these tests.
    monkeypatch.setattr(server, "_env_files", lambda: ())


@pytest.mark.parametrize(
    "line",
    ["BACKEND_TYPE=desktop", "backend_type=desktop", "Backend_Type=DESKTOP", "BACKEND_TYPE=  desktop  "],
)
def test_desktop_setting_in_dotenv_file_is_detected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, line: str) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"{line}\n", encoding="utf-8")
    monkeypatch.setattr(server, "_env_files", lambda: (str(env_file),))
    assert server._legacy_desktop_setting() is True


def test_missing_dotenv_file_is_ignored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(server, "_env_files", lambda: (str(tmp_path / "missing.env"),))
    assert server._legacy_desktop_setting() is False


def test_environment_overrides_dotenv_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("BACKEND_TYPE=desktop\n", encoding="utf-8")
    monkeypatch.setattr(server, "_env_files", lambda: (str(env_file),))
    monkeypatch.setenv("BACKEND_TYPE", "webgui")
    assert server._legacy_desktop_setting() is False


def test_no_warning_without_legacy_setting(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=server.logger.name):
        assert server._warn_legacy_desktop_setting() is False
    assert not caplog.records
    with patch.object(server, "try_get_sap_config", return_value=(None, None)):
        assert "sapgui.mcp" not in server._build_instructions()


def test_backend_type_webgui_is_not_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKEND_TYPE", "webgui")
    assert server._legacy_desktop_setting() is False


@pytest.mark.parametrize("value", ["desktop", "Desktop", "DESKTOP"])
def test_desktop_setting_logs_warning_and_adds_notice(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, value: str
) -> None:
    monkeypatch.setenv("BACKEND_TYPE", value)
    with (
        caplog.at_level(logging.WARNING, logger=server.logger.name),
        patch.object(server, "try_get_sap_config", return_value=(None, None)),
    ):
        instructions = server._build_instructions()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "BACKEND_TYPE=desktop" in warnings[0].getMessage()
    assert "https://github.com/Hochfrequenz/sapgui.mcp" in warnings[0].getMessage()
    assert "https://github.com/Hochfrequenz/sapgui.mcp" in instructions
    assert "SAP GUI for Windows" in instructions
    assert "SAP Web GUI automation server" in instructions  # the server still starts on WebGUI


def test_instructions_carry_no_desktop_guidance() -> None:
    with patch.object(server, "try_get_sap_config", return_value=(None, None)):
        instructions = server._build_instructions()
    assert "COM Scripting" not in instructions
    assert "sap_com_evaluate" not in instructions
    assert "sap-desktop" not in instructions
