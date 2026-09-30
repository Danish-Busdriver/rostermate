from __future__ import annotations

import json
from datetime import datetime, timezone

import app as app_module
import telemetry as telemetry_module
from telemetry import TelemetryClient


class FakeResponse:
    def __init__(self, payload=None):
        self.payload = payload or {"status": "ok"}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def configured_client(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERMATE_TELEMETRY_URL", "https://example.invalid/heartbeat.php")
    monkeypatch.setenv("ROSTERMATE_TELEMETRY_KEY", "ingest-secret")
    return TelemetryClient(tmp_path, tmp_path, "1.2.3")


def test_telemetry_is_enabled_by_default_and_uses_random_uuid(tmp_path, monkeypatch):
    client = configured_client(tmp_path, monkeypatch)

    assert client.load_state() == {"enabled": True}
    state = client.set_enabled(True)

    assert state["enabled"] is True
    assert len(state["installation_id"]) == 36
    assert "driver" not in json.dumps(state).lower()


def test_explicit_telemetry_opt_out_is_preserved(tmp_path, monkeypatch):
    client = configured_client(tmp_path, monkeypatch)
    client.set_enabled(False)

    assert client.load_state()["enabled"] is False
    assert client.send_heartbeat() is False


def test_heartbeat_contains_only_anonymous_installation_fields(tmp_path, monkeypatch):
    client = configured_client(tmp_path, monkeypatch)
    client.set_enabled(True)
    calls = []
    monkeypatch.setattr(telemetry_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(telemetry_module.requests, "post", lambda *args, **kwargs: calls.append((args, kwargs)) or FakeResponse())

    assert client.send_heartbeat(datetime(2026, 8, 9, tzinfo=timezone.utc)) is True
    payload = calls[0][1]["json"]

    assert set(payload) == {"installation_id", "version", "platform"}
    assert payload["platform"] == "windows"
    assert payload["version"] == "1.2.3"
    assert calls[0][1]["headers"]["User-Agent"].startswith("RosterMate-Telemetry/1.2.3")


def test_heartbeat_is_sent_for_every_sync(tmp_path, monkeypatch):
    client = configured_client(tmp_path, monkeypatch)
    client.set_enabled(True)
    calls = []
    monkeypatch.setattr(telemetry_module.requests, "post", lambda *args, **kwargs: calls.append(1) or FakeResponse())
    first = datetime(2026, 8, 9, tzinfo=timezone.utc)

    assert client.send_heartbeat(first) is True
    assert client.send_heartbeat(first) is True
    assert len(calls) == 2


def test_completed_sync_enqueues_heartbeat_on_success_and_failure(monkeypatch):
    heartbeats = []
    monkeypatch.setattr(app_module, "enqueue_sync_heartbeat", lambda: heartbeats.append("sent"))
    monkeypatch.setattr(app_module, "run_initial_sync_core", lambda *args, **kwargs: {"status": "ok"})

    assert app_module.run_initial_sync()["status"] == "ok"

    def fail_sync(*args, **kwargs):
        raise RuntimeError("sync failed")

    monkeypatch.setattr(app_module, "run_initial_sync_core", fail_sync)
    try:
        app_module.run_initial_sync()
    except RuntimeError:
        pass

    assert heartbeats == ["sent", "sent"]


def test_settings_page_explains_consent_and_persists_choice(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_module, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(app_module, "ERROR_LOG_PATH", tmp_path / "logs" / "errors.jsonl")
    app_module.record_error(app_module.ERROR_LOG_PATH, "sync", "SelfService-timeout")
    app_module.record_diagnostic(
        app_module.ERROR_LOG_PATH,
        "sync-timing",
        {"duration_seconds": 16.6, "months": 2, "events": 31},
    )
    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        page = client.get("/1234/settings-page")
        saved = client.post("/1234/settings", data={"app_port": "8080", "anonymous_usage_enabled": "true"})

    assert page.status_code == 200
    assert "Anonym brugsstatistik".encode() in page.data
    assert "chaufførnummer".encode() in page.data
    assert "Fejlfinding".encode() in page.data
    assert "Hent fejlrapport".encode() in page.data
    assert "Seneste sync-tider".encode() in page.data
    assert "Seneste registrerede fejl".encode() not in page.data
    assert saved.get_json()["anonymous_usage_enabled"] is True
    state = json.loads((tmp_path / "telemetry.json").read_text(encoding="utf-8"))
    assert state["enabled"] is True


def test_error_report_contains_runtime_diagnostics_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "ERROR_LOG_PATH", tmp_path / "errors.jsonl")
    app_module.record_error(app_module.ERROR_LOG_PATH, "sync", "password=secret failed")
    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        response = client.get("/1234/error-report")

    report = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "RosterMate lokal fejlrapport" in report
    assert "Runtime:" in report
    assert "secret" not in report
    assert "password=<redacted>" in report


def test_saved_session_test_route_returns_a_clear_result(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_module, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(
        app_module.login_manager,
        "validate_saved_session",
        lambda *_args: (False, "SelfService-sessionen ser ud til at være udløbet."),
    )
    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        response = client.post("/1234/wizard/test-connection")

    assert response.status_code == 400
    assert response.get_json() == {
        "status": "error",
        "message": "SelfService-sessionen ser ud til at være udløbet.",
    }


def test_admin_is_hidden_without_local_key_and_uses_aggregate_stats(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_module, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "output")
    app_module.app.config["TESTING"] = True
    app_module.save_driver_settings("1234", {"wizard_completed": True})

    with app_module.app.test_client() as client:
        assert client.get("/1234/admin").status_code == 404

    monkeypatch.setenv("ROSTERMATE_TELEMETRY_ADMIN_URL", "https://example.invalid/stats.php")
    monkeypatch.setenv("ROSTERMATE_TELEMETRY_ADMIN_KEY", "private-admin-secret")
    monkeypatch.setattr(
        telemetry_module.requests,
        "get",
        lambda *args, **kwargs: FakeResponse({
            "total": 18,
            "active_7_days": 5,
            "active_30_days": 12,
            "active_90_days": 16,
            "new_7_days": 3,
            "new_30_days": 8,
            "platforms": [{"platform": "windows", "count": 7}],
            "versions": [{"version": "1.2.3", "count": 12}],
            "activity": [{"date": datetime.now().date().isoformat(), "installations": 5, "syncs": 7}],
        }),
    )
    with app_module.app.test_client() as client:
        page = client.get("/1234/admin")

    assert page.status_code == 200
    assert b"Aktive installationer" in page.data
    assert b">12<" in page.data
    assert b"Windows" in page.data
    assert b"Sync-aktivitet" in page.data
    assert b"Nye" in page.data
