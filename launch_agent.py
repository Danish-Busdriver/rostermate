from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path


def launch_agent_label(driver_id: str) -> str:
    return f"dk.rostermate.{driver_id}"


def launch_agent_path(driver_id: str, home_dir: Path | None = None) -> Path:
    base_home = home_dir or Path.home()
    return base_home / "Library" / "LaunchAgents" / f"{launch_agent_label(driver_id)}.plist"


def build_launch_agent_plist(driver_id: str, project_dir: Path, output_dir: Path) -> dict[str, object]:
    run_script = project_dir / "run.command"
    stdout_path = output_dir / "launchd.stdout.log"
    stderr_path = output_dir / "launchd.stderr.log"
    return {
        "Label": launch_agent_label(driver_id),
        "ProgramArguments": ["/bin/bash", str(run_script)],
        "WorkingDirectory": str(project_dir),
        "RunAtLoad": True,
        "KeepAlive": False,
        "StandardOutPath": str(stdout_path),
        "StandardErrorPath": str(stderr_path),
        "EnvironmentVariables": {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
        },
    }


def _run_launchctl(command: list[str]) -> None:
    if shutil.which("launchctl") is None:
        return
    subprocess.run(command, check=False, capture_output=True, text=True)


def windows_task_name(driver_id: str) -> str:
    return f"RosterMate-{driver_id}"


def _run_schtasks(command: list[str]) -> None:
    if shutil.which("schtasks") is None:
        return
    subprocess.run(command, check=False, capture_output=True, text=True)


def install_windows_startup(driver_id: str, project_dir: Path) -> Path:
    run_script = project_dir / "run-windows.ps1"
    task_command = f'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{run_script}"'
    _run_schtasks(
        [
            "schtasks",
            "/Create",
            "/TN",
            windows_task_name(driver_id),
            "/TR",
            task_command,
            "/SC",
            "ONLOGON",
            "/RL",
            "LIMITED",
            "/F",
        ]
    )
    return run_script


def remove_windows_startup(driver_id: str, project_dir: Path) -> Path:
    _run_schtasks(["schtasks", "/Delete", "/TN", windows_task_name(driver_id), "/F"])
    return project_dir / "run-windows.ps1"


def install_launch_agent(
    driver_id: str,
    project_dir: Path,
    output_dir: Path,
    home_dir: Path | None = None,
    reload_agent: bool = True,
) -> Path:
    plist_path = launch_agent_path(driver_id, home_dir)
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = build_launch_agent_plist(driver_id, project_dir, output_dir)
    with plist_path.open("wb") as handle:
        plistlib.dump(payload, handle)
    if reload_agent:
        _run_launchctl(["launchctl", "unload", str(plist_path)])
        _run_launchctl(["launchctl", "load", "-w", str(plist_path)])
    return plist_path


def remove_launch_agent(driver_id: str, home_dir: Path | None = None, reload_agent: bool = True) -> Path:
    plist_path = launch_agent_path(driver_id, home_dir)
    if plist_path.exists():
        if reload_agent:
            _run_launchctl(["launchctl", "unload", "-w", str(plist_path)])
        plist_path.unlink()
    return plist_path


def sync_launch_agent_preference(
    driver_id: str,
    enabled: bool,
    project_dir: Path,
    output_dir: Path,
    home_dir: Path | None = None,
    reload_agent: bool = True,
    platform_name: str | None = None,
) -> Path:
    active_platform = platform_name or sys.platform
    if active_platform == "win32":
        if enabled:
            return install_windows_startup(driver_id, project_dir)
        return remove_windows_startup(driver_id, project_dir)
    if enabled:
        return install_launch_agent(driver_id, project_dir, output_dir, home_dir, reload_agent)
    return remove_launch_agent(driver_id, home_dir, reload_agent)
