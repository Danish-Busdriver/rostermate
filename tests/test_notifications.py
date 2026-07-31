from __future__ import annotations

import subprocess

from notifications import change_notification_message, send_change_notification


def test_change_notification_summarizes_all_change_types():
    changes = [
        {"type": "added"},
        {"type": "added"},
        {"type": "changed"},
        {"type": "removed"},
    ]

    assert change_notification_message(changes) == "Vagtplanen er opdateret: 2 tilføjet, 1 ændret, 1 fjernet"


def test_macos_notification_uses_osascript_and_environment():
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))

    assert send_change_notification([{"type": "changed"}], platform_name="darwin", runner=runner)
    command, kwargs = calls[0]
    assert command[0] == "osascript"
    assert kwargs["env"]["ROSTERMATE_NOTIFICATION_MESSAGE"].endswith("1 ændret")


def test_windows_notification_uses_hidden_powershell_balloon():
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))

    assert send_change_notification([{"type": "added"}], platform_name="win32", runner=runner)
    command, kwargs = calls[0]
    assert command[:4] == ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden"]
    assert "System.Windows.Forms.NotifyIcon" in command[-1]
    assert kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)


def test_notification_is_skipped_without_actual_changes():
    assert send_change_notification([], platform_name="darwin", runner=lambda *args, **kwargs: None) is False
