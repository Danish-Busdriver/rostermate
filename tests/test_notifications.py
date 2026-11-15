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


import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
import notifications
from notifications import send_push_notification


class _Response:
    status_code = 200


def test_push_posts_only_short_message_to_topic():
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return _Response()

    assert send_push_notification("rostermate-abc", "Vagtplanen er opdateret: 1 ændret", post=post)
    url, kwargs = calls[0]
    assert url == "https://ntfy.sh/rostermate-abc"
    assert kwargs["data"] == "Vagtplanen er opdateret: 1 ændret".encode("utf-8")
    assert kwargs["headers"] == {"Title": "RosterMate"}
    assert kwargs["timeout"] == 5


def test_push_errors_are_swallowed():
    def post(*_args, **_kwargs):
        raise notifications.requests.ConnectionError("offline")

    assert send_push_notification("rostermate-abc", "besked", post=post) is False


def test_schedule_change_skips_push_when_disabled_and_sends_when_enabled(monkeypatch):
    pushed = []
    monkeypatch.setattr(app_module, "send_change_notification", lambda _changes: False)
    monkeypatch.setattr(app_module, "send_push_notification", lambda topic, message: pushed.append((topic, message)) or True)
    changes = [{"type": "changed", "title": "DO_afløs", "date": "2026-07-08"}]

    app_module.notify_if_schedule_changed({"push_enabled": False, "push_topic": "t"}, changes, had_existing_events=True)
    assert pushed == []

    assert app_module.notify_if_schedule_changed({"push_enabled": True, "push_topic": "t"}, changes, had_existing_events=True)
    assert pushed == [("t", "Vagtplanen er opdateret: 1 ændret")]


def test_failing_push_does_not_break_sync_notification(monkeypatch):
    monkeypatch.setattr(app_module, "send_change_notification", lambda _changes: True)
    monkeypatch.setattr(notifications.requests, "post", lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError()))
    monkeypatch.setattr(app_module, "send_push_notification", lambda topic, message: send_push_notification(topic, message, post=notifications.requests.post))

    assert app_module.notify_if_schedule_changed(
        {"push_enabled": True, "push_topic": "t"}, [{"type": "added"}], had_existing_events=True
    ) is True


def test_new_push_topic_is_random_and_ntfy_safe():
    import re

    first, second = app_module.new_push_topic(), app_module.new_push_topic()
    assert first != second
    assert re.fullmatch(r"[A-Za-z0-9_-]{20,64}", first)


def test_push_test_route_reports_result(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_module, "STORAGE_ROOT", tmp_path)
    app_module.save_driver_settings("1234", {"wizard_completed": True, "push_topic": "rostermate-x"})
    sent = []
    monkeypatch.setattr(app_module, "send_push_notification", lambda topic, message: sent.append(topic) or True)
    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        response = client.post("/1234/push-test")

    assert response.status_code == 200 and sent == ["rostermate-x"]
