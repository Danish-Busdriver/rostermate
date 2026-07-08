from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app import build_event_from_shift, sync_schedule


def test_build_event_from_shift_handles_regular_and_all_day_shifts():
    regular = build_event_from_shift({"id": "DO_afløs", "from": "05:15", "to": "13:02"}, "2026-07-08")
    assert regular["title"] == "DO_afløs"
    assert regular["all_day"] is False
    assert regular["start"].startswith("2026-07-08T05:15")

    holiday = build_event_from_shift({"id": "Fri", "from": "", "to": ""}, "2026-07-10")
    assert holiday["all_day"] is True
    assert holiday["start"].startswith("2026-07-10")


def test_sync_schedule_preserves_events_outside_selected_window(tmp_path):
    existing_events = [
        {
            "id": "old-event",
            "title": "Eksisterende vagter",
            "date": "2026-07-01",
            "start": "2026-07-01T00:00:00",
            "end": "2026-07-01T23:59:59",
            "all_day": True,
        }
    ]

    new_events = [
        {
            "id": "new-event",
            "title": "Ny vagt",
            "date": "2026-07-08",
            "start": "2026-07-08T05:15:00",
            "end": "2026-07-08T13:02:00",
            "all_day": False,
        }
    ]

    updated_events, changes = sync_schedule(
        existing_events=existing_events,
        new_events=new_events,
        window_start="2026-07-08",
        window_end="2026-07-14",
        remove_old_shifts=False,
        output_dir=tmp_path,
    )

    assert any(event["id"] == "old-event" for event in updated_events)
    assert any(event["id"] == "new-event" for event in updated_events)
    assert changes == []


def test_sync_schedule_can_remove_events_outside_selected_window(tmp_path):
    existing_events = [
        {
            "id": "old-event",
            "title": "Eksisterende vagt",
            "date": "2026-07-01",
            "start": "2026-07-01T00:00:00",
            "end": "2026-07-01T23:59:59",
            "all_day": True,
        }
    ]

    updated_events, changes = sync_schedule(
        existing_events=existing_events,
        new_events=[],
        window_start="2026-07-08",
        window_end="2026-07-14",
        remove_old_shifts=True,
        output_dir=tmp_path,
    )

    assert all(event["id"] != "old-event" for event in updated_events)
    assert changes == []


def test_sync_schedule_does_not_duplicate_existing_events(tmp_path):
    existing_events = [
        {
            "id": "same-event",
            "title": "Samme vagt",
            "date": "2026-07-08",
            "start": "2026-07-08T05:15:00",
            "end": "2026-07-08T13:02:00",
            "all_day": False,
        }
    ]
    new_events = [
        {
            "id": "same-event",
            "title": "Samme vagt",
            "date": "2026-07-08",
            "start": "2026-07-08T05:15:00",
            "end": "2026-07-08T13:02:00",
            "all_day": False,
        }
    ]

    updated_events, changes = sync_schedule(
        existing_events=existing_events,
        new_events=new_events,
        window_start="2026-07-08",
        window_end="2026-07-14",
        remove_old_shifts=False,
        output_dir=tmp_path,
    )

    assert len(updated_events) == 1
    assert updated_events[0]["id"] == "same-event"
    assert changes == []


def test_settings_route_persists_selfservice_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_module, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(app_module, "HISTORY_PATH", tmp_path / "data" / "history.json")
    monkeypatch.setattr(app_module, "PLAN_PATH", tmp_path / "data" / "plan.json")
    monkeypatch.setattr(app_module, "SETTINGS_PATH", tmp_path / "data" / "settings.json")
    monkeypatch.setattr(app_module, "SCHEDULE_PATH", tmp_path / "output" / "schedule.json")
    monkeypatch.setattr(app_module, "EVENTS_STORE_PATH", tmp_path / "output" / "events_store.json")
    monkeypatch.setattr(app_module, "CHANGES_PATH", tmp_path / "output" / "changes.json")
    monkeypatch.setattr(app_module, "ICS_PATH", tmp_path / "output" / "vagter.ics")

    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        response = client.post(
            "/settings",
            data={
                "url": "https://selfservice.example",
                "user": "tester",
                "pass": "secret",
                "remove_old_shifts": "false",
            },
        )

    assert response.status_code == 200
    settings = app_module.load_settings()
    assert settings["url"] == "https://selfservice.example"
    assert settings["user"] == "tester"
    assert settings["pass"] == "secret"
