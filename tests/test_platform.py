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

    for filename in (
        "install-windows.cmd",
        "install-windows.ps1",
        "run-windows.cmd",
        "run-windows.ps1",
        "uninstall-windows.cmd",
        "uninstall-windows.ps1",
    ):
        assert (project_root / filename).is_file()

    installer = (project_root / "install-windows.ps1").read_text(encoding="utf-8")
    launcher = (project_root / "run-windows.ps1").read_text(encoding="utf-8")
    assert "playwright install chromium" in installer
    assert "python.org/ftp/python" in installer
    assert "Test-RosterMateVenv" in installer
    assert 'Test-Path $Config' in installer
    assert 'Remove-Item ".venv" -Recurse -Force' in installer
    assert 'Join-Path $env:LOCALAPPDATA "RosterMate"' in installer
    assert '"RosterMate.lnk"' in installer
    assert "windows_launcher.py" in launcher
    windows_launcher = (project_root / "windows_launcher.py").read_text(encoding="utf-8")
    assert "auto_update.py" in windows_launcher
    assert "ensure_available_port" in windows_launcher
    assert "start_tray" in windows_launcher
    assert 'http://localhost:{port}/wizard/' in windows_launcher


def test_windows_exe_installer_definition_is_present():
    project_root = Path(__file__).resolve().parents[1]
    installer = (project_root / "installer" / "windows" / "RosterMate.iss").read_text(encoding="utf-8")
    workflow = (project_root / ".github" / "workflows" / "windows-installer.yml").read_text(encoding="utf-8")

    assert "PrivilegesRequired=lowest" in installer
    assert "install-windows.ps1" in installer
    assert "run-windows.cmd" in installer
    assert "[UninstallDelete]" in installer
    assert "ISCC.exe" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "Install and launch packaged application" in workflow
    assert "Tray-ikonprocessen kører ikke" in workflow
    assert "SetupIconFile=" in installer
    assert "RosterMate.ico" in installer
    assert "Afinstaller RosterMate" in installer
    assert "[UninstallRun]" in installer
    assert "RosterMate.app\\*" in installer
    assert "install.command" in installer


def test_macos_app_bootstraps_first_install_and_checks_version():
    project_root = Path(__file__).resolve().parents[1]
    launcher = (project_root / "RosterMate.app" / "Contents" / "MacOS" / "RosterMate").read_text(encoding="utf-8")

    assert "./install.command" in launcher
    assert "EXPECTED_VERSION=" in launcher
    assert 'curl -fsS "http://127.0.0.1:$PORT/health"' in launcher
    assert "Første installation kan tage et par minutter" in launcher
    run_script = (project_root / "run.command").read_text(encoding="utf-8")
    assert 'python3 tray.py --server-pid "$server_pid"' in run_script
    assert 'wait "$server_pid"' in launcher
    assert 'http://localhost:$PORT/wizard/' in launcher
    assert (project_root / "uninstall.command").is_file()
    uninstaller = (project_root / "uninstall.command").read_text(encoding="utf-8")
    assert "RosterMate Backup" in uninstaller
    assert 'mv "$SCRIPT_DIR" "$destination"' in uninstaller


def test_macos_pkg_installer_is_present_and_self_contained():
    project_root = Path(__file__).resolve().parents[1]
    builder = (project_root / "build-macos-pkg.command").read_text(encoding="utf-8")
    postinstall = (project_root / "installer" / "macos" / "scripts" / "postinstall").read_text(
        encoding="utf-8"
    )
    workflow = (project_root / ".github" / "workflows" / "macos-installer.yml").read_text(
        encoding="utf-8"
    )

    assert "pkgbuild" in builder
    assert "productbuild" in builder
    assert "/Applications/RosterMate" in builder
    assert 'python-$PYTHON_VERSION-macos11.pkg' in postinstall
    assert "install.command" in postinstall
    assert "RosterMate.app" in postinstall
    assert "actions/upload-artifact@v4" in workflow
    assert "Validate package contents" in workflow
    assert '"$PAYLOAD_DIR/windows_launcher.py"' in builder
    assert "Payload/install-windows.ps1" in workflow


def test_shared_tray_uses_the_rostermate_logo_and_expected_actions():
    project_root = Path(__file__).resolve().parents[1]
    tray = (project_root / "tray.py").read_text(encoding="utf-8")

    assert '"static" / "Rostermate.png"' in tray
    assert "Åbn RosterMate" in tray
    assert "Afslut RosterMate" in tray
    assert (project_root / "assets" / "RosterMate.ico").is_file()
