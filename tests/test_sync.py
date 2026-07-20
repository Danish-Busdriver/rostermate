from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app import build_event_from_shift, select_next_calendar_events, sync_schedule


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


def test_select_next_calendar_events_excludes_past_and_limits_to_seven():
    events = [
        {"id": "past", "date": "2026-07-19", "start": "2026-07-19T08:00:00"},
        {"id": "invalid", "date": "not-a-date", "start": ""},
        *[
            {
                "id": f"future-{index}",
                "date": f"2026-07-{20 + index:02d}",
                "start": f"2026-07-{20 + index:02d}T08:00:00",
            }
            for index in range(9)
        ],
    ]

    selected = select_next_calendar_events(events, today=app_module.date(2026, 7, 20))

    assert [event["id"] for event in selected] == [f"future-{index}" for index in range(7)]


def test_select_next_calendar_events_sorts_same_day_by_start_time():
    events = [
        {"id": "late", "date": "2026-07-20", "start": "2026-07-20T14:00:00"},
        {"id": "early", "date": "2026-07-20", "start": "2026-07-20T06:00:00"},
    ]

    selected = select_next_calendar_events(events, today=app_module.date(2026, 7, 20))

    assert [event["id"] for event in selected] == ["early", "late"]


def test_settings_route_persists_selfservice_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_module, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "output")

    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        response = client.post(
            "/1234/settings",
            data={
                "url": "https://selfservice.example",
                "user": "tester",
                "pass": "secret",
                "remove_old_shifts": "false",
            },
        )

        second_response = client.post(
            "/5678/settings",
            data={
                "url": "https://selfservice.other",
                "user": "other",
                "pass": "secret-2",
                "remove_old_shifts": "false",
            },
        )

    assert response.status_code == 200
    assert second_response.status_code == 200

    first_settings = app_module.load_settings("1234")
    second_settings = app_module.load_settings("5678")

    assert first_settings["url"] == "https://selfservice.example"
    assert first_settings["user"] == "tester"
    assert first_settings["pass"] == "secret"
    assert second_settings["url"] == "https://selfservice.other"
    assert second_settings["user"] == "other"
    assert second_settings["pass"] == "secret-2"


def test_new_driver_redirects_to_wizard(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_module, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "output")

    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        response = client.post("/", data={"driver_id": "1234"}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/1234/wizard")


def test_wizard_complete_persists_preferences_and_redirects(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_module, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(app_module, "sync_launch_agent_preference", lambda *args, **kwargs: None)

    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        response = client.post(
            "/1234/wizard/complete",
            data={
                "calendar_name": "Min Vagtplan",
                "days_ahead": "14",
                "keep_old_shifts": "true",
                "launch_at_login": "true",
                "show_menu_bar_icon": "true",
                "notify_on_changes": "true",
            },
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/1234/")

    settings = app_module.load_settings("1234")
    assert settings["calendar_name"] == "Min Vagtplan"
    assert settings["days_ahead"] == 14
    assert settings["keep_old_shifts"] is True
    assert settings["remove_old_shifts"] is False
    assert settings["wizard_completed"] is True
