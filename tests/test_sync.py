from pathlib import Path

import sys
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app import build_event_from_shift, build_events_from_shift_rows, calendar_months_in_range, sync_schedule


def test_build_event_from_shift_handles_regular_and_all_day_shifts():
    regular = build_event_from_shift({"id": "DO_afløs", "from": "05:15", "to": "13:02"}, "2026-07-08")
    assert regular["title"] == "DO_afløs"
    assert regular["id"] == "2026-07-08|DO_afløs|05:15|13:02"
    assert regular["all_day"] is False
    assert regular["start"].startswith("2026-07-08T05:15")

    holiday = build_event_from_shift({"id": "Fri", "from": "", "to": ""}, "2026-07-10")
    assert holiday["all_day"] is True
    assert holiday["start"].startswith("2026-07-10")


def test_build_events_from_shift_rows_crosses_month_boundary():
    rows = [
        {"day_number": 20, "title": "DO_afl", "from": "05:15", "to": "13:02"},
        {"day_number": 21, "title": "AFTEN", "from": "12:00", "to": "20:00"},
        {"day_number": 1, "title": "NAT", "from": "22:00", "to": "06:00"},
    ]

    events = build_events_from_shift_rows(
        rows=rows,
        page_month=date(2026, 7, 1),
        window_start=date(2026, 7, 20),
        window_end=date(2026, 8, 2),
    )

    assert [event["date"] for event in events] == ["2026-07-20", "2026-07-21", "2026-08-01"]
    assert events[-1]["end"] == "2026-08-02T06:00:00"


def test_calendar_months_in_range_includes_next_month():
    months = calendar_months_in_range(date(2026, 7, 20), date(2026, 8, 19))

    assert months == [date(2026, 7, 1), date(2026, 8, 1)]


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


def test_sync_route_uses_saved_remove_old_shifts_setting(tmp_path, monkeypatch):
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

    app_module.ensure_storage()
    app_module.save_json(
        app_module.EVENTS_STORE_PATH,
        [
            {
                "id": "old-event",
                "title": "Gammel vagt",
                "date": "2026-07-01",
                "start": "2026-07-01T00:00:00",
                "end": "2026-07-01T23:59:59",
                "all_day": True,
            }
        ],
    )
    app_module.save_settings(
        {
            "url": "https://selfservice.example",
            "user": "tester",
            "pass": "secret",
            "days_ahead": 7,
            "run_every_minutes": 60,
            "remove_old_shifts": True,
            "employment_type": "ramme_ansat",
        }
    )
    monkeypatch.setattr(
        app_module,
        "fetch_selfservice_schedule",
        lambda days_ahead: (
            [
                {
                    "id": "2026-07-20|Ny vagt|05:15|13:02",
                    "title": "Ny vagt",
                    "date": "2026-07-20",
                    "start": "2026-07-20T05:15:00",
                    "end": "2026-07-20T13:02:00",
                    "all_day": False,
                }
            ],
            "Synkronisering gennemført - 1 vagter hentet",
        ),
    )

    class FrozenDate(date):
        @classmethod
        def today(cls) -> "FrozenDate":
            return cls(2026, 7, 20)

    monkeypatch.setattr(app_module, "date", FrozenDate)
    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        response = client.post("/sync", data={"days_ahead": "7"})

    assert response.status_code == 200
    updated_events = app_module.load_json(app_module.EVENTS_STORE_PATH, [])
    assert [event["title"] for event in updated_events] == ["Ny vagt"]
