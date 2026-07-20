from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app import build_event_from_shift, list_driver_ids, select_next_calendar_events, software_info, sync_schedule, valid_google_client_id, write_outputs
from sync import fetch_status_is_error, run_initial_sync


def test_build_event_from_shift_handles_regular_and_all_day_shifts():
    regular = build_event_from_shift({"id": "DO_afløs", "from": "05:15", "to": "13:02"}, "2026-07-08")
    assert regular["title"] == "DO_afløs"
    assert regular["all_day"] is False
    assert regular["start"].startswith("2026-07-08T05:15")

    holiday = build_event_from_shift({"id": "Fri", "from": "", "to": ""}, "2026-07-10")
    assert holiday["all_day"] is True
    assert holiday["start"].startswith("2026-07-10")


def test_write_outputs_creates_rfc5545_calendar(tmp_path):
    write_outputs(
        [
            {
                "id": "timed",
                "title": "DO_afløs",
                "date": "2026-07-21",
                "start": "2026-07-21T06:00:00+02:00",
                "end": "2026-07-21T14:00:00+02:00",
                "all_day": False,
            },
            {
                "id": "day-off",
                "title": "Fri",
                "date": "2026-07-22",
                "start": "2026-07-22",
                "end": "2026-07-23",
                "all_day": True,
            },
        ],
        [],
        tmp_path,
    )

    calendar = (tmp_path / "vagter.ics").read_bytes()
    assert b"DTSTART:20260721T040000Z\r\n" in calendar
    assert b"DTEND:20260721T120000Z\r\n" in calendar
    assert b"DTSTART;VALUE=DATE:20260722\r\n" in calendar
    assert b"DTEND;VALUE=DATE:20260723\r\n" in calendar
    assert b"+0200" not in calendar


def test_google_client_id_requires_google_oauth_format():
    assert valid_google_client_id("123456-example.apps.googleusercontent.com") is True
    assert valid_google_client_id("dkbusdriver") is False
    assert valid_google_client_id("") is False


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


def test_software_info_exposes_version_and_survives_missing_git(tmp_path):
    info = software_info(tmp_path)

    assert info["version"] == app_module.APP_VERSION
    assert info["commit"] == "ukendt"
    assert info["updated_at"] == "ukendt"


def test_list_driver_ids_only_returns_configured_numeric_profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path)
    (tmp_path / "15831").mkdir()
    (tmp_path / "15831" / "settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "empty").mkdir()
    (tmp_path / "empty" / "settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "999").mkdir()
    (tmp_path / "999" / "settings.json").touch()

    assert list_driver_ids() == ["15831"]


def test_fetch_status_distinguishes_errors_from_empty_schedule():
    assert fetch_status_is_error("SelfService-sessionen er udløbet") is True
    assert fetch_status_is_error("Login mislykkedes - tjek login") is True
    assert fetch_status_is_error("Ingen vagter fundet i kalenderen - muligvis ingen vagter planlagt") is False


def test_initial_sync_does_not_report_old_events_as_new_when_fetch_fails(tmp_path):
    paths = {
        "events_store_path": tmp_path / "events.json",
        "history_path": tmp_path / "history.json",
        "output_dir": tmp_path,
    }

    try:
        run_initial_sync(
            "15831",
            {"days_ahead": 7},
            paths,
            lambda _days, _driver: ([], "SelfService-sessionen er udløbet"),
            lambda *args: (args[0], []),
            lambda *_args: None,
            lambda _path, _default: [{"id": "old"}],
            lambda _path: [],
            lambda *_args: None,
        )
    except RuntimeError as exc:
        assert str(exc) == "SelfService-sessionen er udløbet"
    else:
        raise AssertionError("Expected the failed fetch to stop the initial sync")


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


def test_wizard_preferences_renders_shift_preview():
    template = app_module.app.jinja_env.from_string(app_module.WIZARD_PREFERENCES_TEMPLATE)

    rendered = template.render(
        settings=app_module.with_setup_defaults({}),
        preview=[
            {
                "weekday": "Mandag",
                "items": [{"title": "Vagt 42", "time_label": "08:00–16:00"}],
            }
        ],
        preview_count=1,
        urls={
            "wizard_complete_url": "/1234/wizard/complete",
            "wizard_url": "/1234/wizard",
            "wizard_test_connection_url": "/1234/wizard/test-connection",
        },
    )

    assert "Vagt 42" in rendered
    assert "08:00–16:00" in rendered
