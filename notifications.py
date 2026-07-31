from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, Callable


Runner = Callable[..., Any]


def change_notification_message(changes: list[dict[str, Any]]) -> str:
    counts = {"added": 0, "changed": 0, "removed": 0}
    for change in changes:
        change_type = str(change.get("type", ""))
        if change_type in counts:
            counts[change_type] += 1
    parts = []
    labels = (("added", "tilføjet"), ("changed", "ændret"), ("removed", "fjernet"))
    for key, label in labels:
        if counts[key]:
            parts.append(f"{counts[key]} {label}")
    return "Vagtplanen er opdateret: " + ", ".join(parts) if parts else ""


def send_change_notification(
    changes: list[dict[str, Any]],
    *,
    platform_name: str | None = None,
    runner: Runner = subprocess.Popen,
) -> bool:
    message = change_notification_message(changes)
    if not message:
        return False
    active_platform = platform_name or sys.platform
    environment = {**os.environ, "ROSTERMATE_NOTIFICATION_MESSAGE": message}

    try:
        if active_platform == "darwin":
            runner(
                [
                    "osascript",
                    "-e",
                    'display notification (system attribute "ROSTERMATE_NOTIFICATION_MESSAGE") with title "RosterMate"',
                ],
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        if active_platform == "win32":
            script = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "Add-Type -AssemblyName System.Drawing;"
                "$n=New-Object System.Windows.Forms.NotifyIcon;"
                "$n.Icon=[System.Drawing.SystemIcons]::Information;"
                "$n.Visible=$true;"
                "$n.ShowBalloonTip(7000,'RosterMate',$env:ROSTERMATE_NOTIFICATION_MESSAGE,"
                "[System.Windows.Forms.ToolTipIcon]::Info);"
                "Start-Sleep -Seconds 8;"
                "$n.Dispose()"
            )
            runner(
                ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
    except OSError:
        return False
    return False
