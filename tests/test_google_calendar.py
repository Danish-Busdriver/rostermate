from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from settings import google_calendar_display_name


class _Result:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class _Calendars:
    def __init__(self, existing=None):
        self.existing = existing
        self.inserted_body = None
        self.patched_body = None

    def get(self, calendarId):
        return _Result(self.existing or {"id": calendarId, "summary": "RosterMate"})

    def insert(self, body):
        self.inserted_body = body
        return _Result({"id": "created-calendar-id", **body})

    def patch(self, calendarId, body):
        self.patched_body = {"calendarId": calendarId, **body}
        return _Result({"id": calendarId, **body})


class _CalendarService:
    def __init__(self, existing=None):
        self.calendar_resource = _Calendars(existing)

    def calendars(self):
        return self.calendar_resource


def test_legacy_google_calendar_id_is_not_shown_as_the_calendar_name():
    assert google_calendar_display_name("abc123@group.calendar.google.com") == "RosterMate"
    assert google_calendar_display_name("primary") == "RosterMate"
    assert google_calendar_display_name("Mine vagter") == "Mine vagter"


def test_google_calendar_is_created_with_editable_default_name():
    service = _CalendarService()

    calendar_id = app_module.ensure_google_calendar(
        {"google_calendar_name": "Min Vagtplan", "google_calendar_id": ""},
        credentials=object(),
        service=service,
    )

    assert calendar_id == "created-calendar-id"
    assert service.calendar_resource.inserted_body == {
        "summary": "Min Vagtplan",
        "timeZone": "Europe/Copenhagen",
    }


def test_existing_google_calendar_is_renamed_without_creating_another():
    service = _CalendarService({"id": "calendar-id", "summary": "RosterMate"})

    calendar_id = app_module.ensure_google_calendar(
        {"google_calendar_name": "Mine vagter", "google_calendar_id": "calendar-id"},
        credentials=object(),
        service=service,
    )

    assert calendar_id == "calendar-id"
    assert service.calendar_resource.patched_body == {
        "calendarId": "calendar-id",
        "summary": "Mine vagter",
    }
    assert service.calendar_resource.inserted_body is None


def test_google_callback_stores_created_calendar_id(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_module, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "output")
    app_module.ensure_storage("1234")
    app_module.save_driver_settings(
        "1234",
        {
            "google_client_id": "123456-example.apps.googleusercontent.com",
            "google_client_secret": "test-secret",
            "google_calendar_name": "Mine vagter",
        },
    )

    class Credentials:
        def to_json(self):
            return json.dumps({"token": "test-token"})

    class Flow:
        credentials = Credentials()

        def fetch_token(self, authorization_response):
            assert "code=test-code" in authorization_response

    monkeypatch.setattr(app_module, "google_dependencies_available", lambda: (True, ""))
    monkeypatch.setattr(app_module, "create_google_flow", lambda *args, **kwargs: Flow())
    monkeypatch.setattr(app_module, "ensure_google_calendar", lambda settings, credentials: "new-calendar-id")

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        with client.session_transaction() as flask_session:
            flask_session["google_oauth_state"] = "state"
            flask_session["google_oauth_driver_id"] = "1234"
        response = client.get("/1234/google/callback?code=test-code", follow_redirects=False)

    saved = app_module.load_settings("1234")
    assert response.status_code == 302
    assert saved["google_calendar_id"] == "new-calendar-id"
    assert saved["google_calendar_name"] == "Mine vagter"
