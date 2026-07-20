from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
import launch_agent as launch_agent_module


def test_windows_storage_uses_local_app_data(monkeypatch):
    monkeypatch.delenv("ROSTERMATE_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\Tester\AppData\Local")

    storage_root = app_module.default_storage_root("win32")

    assert storage_root == Path(r"C:\Users\Tester\AppData\Local") / "RosterMate"


def test_macos_storage_remains_in_project_directory(monkeypatch):
    monkeypatch.delenv("ROSTERMATE_HOME", raising=False)

    assert app_module.default_storage_root("darwin") == app_module.BASE_DIR


def test_storage_root_can_be_overridden_on_both_platforms(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERMATE_HOME", str(tmp_path / "custom-data"))

    assert app_module.default_storage_root("darwin") == tmp_path / "custom-data"
    assert app_module.default_storage_root("win32") == tmp_path / "custom-data"


def test_windows_startup_creates_logon_task(tmp_path, monkeypatch):
    commands: list[list[str]] = []
    monkeypatch.setattr(launch_agent_module, "_run_schtasks", commands.append)

    result = launch_agent_module.sync_launch_agent_preference(
        "12345",
        True,
        tmp_path,
        tmp_path / "output",
        platform_name="win32",
    )

    assert result == tmp_path / "run-windows.ps1"
    assert commands == [
        [
            "schtasks",
            "/Create",
            "/TN",
            "RosterMate-12345",
            "/TR",
            f'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{tmp_path / "run-windows.ps1"}"',
            "/SC",
            "ONLOGON",
            "/RL",
            "LIMITED",
            "/F",
        ]
    ]


def test_windows_startup_can_be_removed(tmp_path, monkeypatch):
    commands: list[list[str]] = []
    monkeypatch.setattr(launch_agent_module, "_run_schtasks", commands.append)

    launch_agent_module.sync_launch_agent_preference(
        "12345",
        False,
        tmp_path,
        tmp_path / "output",
        platform_name="win32",
    )

    assert commands == [["schtasks", "/Delete", "/TN", "RosterMate-12345", "/F"]]


def test_windows_distribution_files_are_present():
    project_root = Path(__file__).resolve().parents[1]

    for filename in ("install-windows.cmd", "install-windows.ps1", "run-windows.cmd", "run-windows.ps1"):
        assert (project_root / filename).is_file()

    installer = (project_root / "install-windows.ps1").read_text(encoding="utf-8")
    launcher = (project_root / "run-windows.ps1").read_text(encoding="utf-8")
    assert "playwright install chromium" in installer
    assert 'Join-Path $env:LOCALAPPDATA "RosterMate"' in installer
    assert '"RosterMate.lnk"' in installer
    assert "auto_update.py" in launcher
    assert 'Invoke-WebRequest -UseBasicParsing -Uri "$AppUrl/health"' in launcher
