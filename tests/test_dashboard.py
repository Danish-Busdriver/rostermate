from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard import should_show_first_run, should_show_welcome_back
from session_store import SelfServiceSessionStore


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
