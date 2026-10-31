from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard import should_show_first_run, should_show_welcome_back
from session_store import SelfServiceSessionStore
import app as app_module


def session_store(tmp_path, *, saved: bool) -> SelfServiceSessionStore:
    store = SelfServiceSessionStore("12345", tmp_path / "state.json", tmp_path / "profile")
    if saved:
        store.storage_state_path.write_text('{"cookies":[]}', encoding="utf-8")
    return store


def test_saved_but_unverified_session_opens_dashboard_without_claiming_connected(tmp_path):
    store = session_store(tmp_path, saved=True)
    settings = {"wizard_completed": True, "selfservice_session_verified": False}

    assert should_show_first_run(settings, store) is False
    assert should_show_welcome_back(settings, store) is False


def test_verified_saved_session_shows_welcome_back(tmp_path):
    store = session_store(tmp_path, saved=True)
    settings = {"wizard_completed": True, "selfservice_session_verified": True}

    assert should_show_first_run(settings, store) is False
    assert should_show_welcome_back(settings, store) is True


def test_existing_calendar_data_never_locks_user_in_first_run(tmp_path):
    store = session_store(tmp_path, saved=False)

    assert should_show_first_run({}, store, has_existing_data=True) is False


def test_dashboard_renders_without_settings_only_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_module, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(app_module, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(
        app_module,
        "check_for_release_update",
        lambda *_args, **_kwargs: {"available": False},
    )
    paths = app_module.get_driver_paths("1234")
    app_module.save_driver_settings("1234", {"wizard_completed": True})
    paths["selfservice_storage_state_path"].write_text('{"cookies":[]}', encoding="utf-8")
    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        response = client.get("/1234/")

    assert response.status_code == 200
    assert b"Dashboard" in response.data
    assert b"Seneste registrerede fejl" not in response.data


def test_today_tomorrow_shows_shifts_and_marks_empty_days():
    today = app_module.date(2026, 11, 3)
    events = [
        app_module.build_event_from_shift({"id": "Ops3", "from": "09:05", "to": "16:54"}, "2026-11-03"),
    ]

    cards = app_module.build_today_tomorrow(events, today)

    assert [card["label"] for card in cards] == ["I dag", "I morgen"]
    assert cards[0]["shifts"][0]["title"] == "Ops3"
    assert cards[0]["shifts"][0]["time_label"] == "09:05 - 16:54"
    assert cards[1]["shifts"] == []


def test_change_description_shows_weekday_and_before_after():
    old = app_module.build_event_from_shift({"id": "Ops3", "from": "09:05", "to": "16:54"}, "2026-11-04")
    new = app_module.build_event_from_shift({"id": "Ops3", "from": "10:05", "to": "17:54"}, "2026-11-04")

    described = app_module.describe_change({"type": "changed", "id": new["id"], "old": old, "new": new})

    assert described["date_label"] == "Ons 04.11"
    assert described["detail"] == "09:05 - 16:54 -> 10:05 - 17:54"
    assert described["badge_text"] == "Opdateret"
