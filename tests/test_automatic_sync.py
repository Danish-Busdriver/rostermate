from __future__ import annotations

from datetime import datetime

import app as app_module
from automatic_sync import (
    LAST_ATTEMPT_KEY,
    RAMME_KEY,
    TIMELOENNET_KEY,
    THURSDAY_KEY,
    TUESDAY_KEY,
    automatic_sync_slot,
    ensure_automatic_sync_times,
    next_automatic_sync,
    schedule_summary,
)


class FixedRandom:
    def __init__(self, values: list[int]):
        self.values = iter(values)

    def randint(self, start: int, end: int) -> int:
        value = next(self.values)
        assert start <= value <= end
        return value


def test_random_times_are_created_once_inside_the_required_windows():
    settings, changed = ensure_automatic_sync_times(
        {"employment_type": "ramme_ansat"},
        FixedRandom([12 * 60 + 7, 11 * 60 + 23, 9 * 60 + 11, 15 * 60 + 59]),
    )

    assert changed is True
    assert settings["automatic_sync_times"] == {
        RAMME_KEY: "12:07",
        TIMELOENNET_KEY: "11:23",
        TUESDAY_KEY: "09:11",
        THURSDAY_KEY: "15:59",
    }

    unchanged, changed_again = ensure_automatic_sync_times(settings, FixedRandom([]))
    assert changed_again is False
    assert unchanged == settings


def test_ramme_sync_is_due_once_daily_inside_the_12_to_14_window():
    settings = {
        "employment_type": "ramme_ansat",
        "automatic_sync_times": {RAMME_KEY: "12:37"},
    }
    now = datetime(2026, 7, 31, 12, 37)
    slot = automatic_sync_slot(settings, now)

    assert slot == "2026-07-31:ramme_daily"
    assert automatic_sync_slot({**settings, LAST_ATTEMPT_KEY: slot}, now) is None
    assert automatic_sync_slot(settings, datetime(2026, 7, 31, 11, 59)) is None
    assert automatic_sync_slot(settings, datetime(2026, 7, 31, 14, 0)) is None


def test_turnus_sync_uses_tuesday_and_thursday_between_9_and_16():
    settings = {
        "employment_type": "fast_turnus",
        "automatic_sync_times": {
            TUESDAY_KEY: "10:15",
            THURSDAY_KEY: "14:45",
        },
    }

    assert automatic_sync_slot(settings, datetime(2026, 7, 28, 10, 15)) == "2026-07-28:turnus_tuesday"
    assert automatic_sync_slot(settings, datetime(2026, 7, 30, 14, 45)) == "2026-07-30:turnus_thursday"
    assert automatic_sync_slot(settings, datetime(2026, 7, 31, 14, 45)) is None
    assert schedule_summary(settings) == "Tirsdag kl. 10:15 og torsdag kl. 14:45"


def test_timeloennet_sync_is_due_once_daily_between_9_and_16():
    settings = {
        "employment_type": "timeloennet",
        "automatic_sync_times": {TIMELOENNET_KEY: "11:23"},
    }
    now = datetime(2026, 7, 31, 11, 23)
    slot = automatic_sync_slot(settings, now)

    assert slot == "2026-07-31:timeloennet_daily"
    assert automatic_sync_slot({**settings, LAST_ATTEMPT_KEY: slot}, now) is None
    assert automatic_sync_slot(settings, datetime(2026, 7, 31, 8, 59)) is None
    assert automatic_sync_slot(settings, datetime(2026, 7, 31, 16, 0)) is None
    assert schedule_summary(settings) == "Dagligt kl. 11:23"


def test_next_automatic_sync_uses_the_profiles_stable_time():
    settings = {
        "employment_type": "ramme_ansat",
        "automatic_sync_times": {RAMME_KEY: "13:12"},
    }

    assert next_automatic_sync(settings, datetime(2026, 7, 31, 10, 0)) == datetime(2026, 7, 31, 13, 12)
    assert next_automatic_sync(settings, datetime(2026, 7, 31, 13, 13)) == datetime(2026, 8, 1, 13, 12)


def test_automatic_cycle_runs_a_profile_only_once_per_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_module, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "output")
    paths = app_module.get_driver_paths("1234")
    app_module.save_driver_settings(
        "1234",
        {
            "wizard_completed": True,
            "selfservice_session_verified": True,
            "employment_type": "ramme_ansat",
            "automatic_sync_times": {
                RAMME_KEY: "12:30",
                TUESDAY_KEY: "10:00",
                THURSDAY_KEY: "11:00",
            },
        },
    )
    paths["selfservice_storage_state_path"].write_text('{"cookies":[]}', encoding="utf-8")
    calls = []

    def fake_initial_sync(*args, **kwargs):
        calls.append((args, kwargs))
        return {"message": "ok"}

    monkeypatch.setattr(app_module, "run_initial_sync", fake_initial_sync)
    now = datetime(2026, 7, 31, 12, 31)

    first = app_module.run_automatic_sync_cycle(now)
    second = app_module.run_automatic_sync_cycle(now)

    assert first[0]["status"] == "synced"
    assert second == []
    assert len(calls) == 1
    assert app_module.load_settings("1234")[LAST_ATTEMPT_KEY] == "2026-07-31:ramme_daily"


def test_failed_automatic_cycle_is_not_retried_inside_the_same_window(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_module, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "output")
    paths = app_module.get_driver_paths("9876")
    app_module.save_driver_settings(
        "9876",
        {
            "wizard_completed": True,
            "employment_type": "ramme_ansat",
            "automatic_sync_times": {
                RAMME_KEY: "12:30",
                TUESDAY_KEY: "10:00",
                THURSDAY_KEY: "11:00",
            },
        },
    )
    paths["selfservice_storage_state_path"].write_text('{"cookies":[]}', encoding="utf-8")
    calls = []

    def failing_initial_sync(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("SelfService er midlertidigt utilgÃ¦ngelig")

    monkeypatch.setattr(app_module, "run_initial_sync", failing_initial_sync)
    now = datetime(2026, 7, 31, 12, 31)

    first = app_module.run_automatic_sync_cycle(now)
    second = app_module.run_automatic_sync_cycle(datetime(2026, 7, 31, 12, 45))

    assert first[0]["status"] == "error"
    assert second == []
    assert calls == [1]
    assert "Automatisk synkronisering fejlede" in app_module.load_history(paths["history_path"])[-1]["summary"]
