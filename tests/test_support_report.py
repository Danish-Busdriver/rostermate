from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
import support_report
from support_report import build_support_report, scrub
from telemetry import TelemetryClient


def test_scrub_removes_personal_identifiers():
    text = (
        "fejl i /Users/hanne/Library/x og C:\\Users\\Hanne\\AppData for 16134 "
        "fra 192.168.0.29 hanne@example.dk calendar.ics?token=abc123 localhost 127.0.0.1"
    )
    result = scrub(text, ["16134"])
    for leaked in ("hanne", "Hanne", "16134", "192.168.0.29", "example.dk", "abc123"):
        assert leaked not in result
    assert "/Users/<bruger>/Library" in result and "127.0.0.1" in result


def test_report_contains_app_info_but_no_driver_data(monkeypatch):
    monkeypatch.setattr(support_report, "local_identifiers", lambda: ["daniels-mac", "daniel"])
    profiles = {
        "16134": {
            "user": "selfservice-login",
            "pass": "hemmeligt-kodeord",
            "calendar_access_token": "kalendertoken",
            "push_topic": "rostermate-pushemne",
            "calendar_public_base_url": "https://vagter.mitdomaene.dk",
            "employment_type": "ramme_ansat",
            "last_automatic_sync_status": "error",
            "last_automatic_sync_message": "Login fejlede for selfservice-login på daniels-mac",
        },
        "15831": {},
    }
    log = [{
        "timestamp": "2026-11-14T12:07:24+00:00", "component": "manual-sync", "error_type": "RuntimeError",
        "category": "ukendt", "message": "Executable doesn't exist at /Users/daniel/Library/Caches/ms-playwright",
        "context": {"driver_id": "16134", "duration_seconds": "0.2"},
    }]

    report = build_support_report(
        version="1.17.0", commit="abc1234", profiles=profiles, log_entries=log,
        runtime={"python_version": "3.14.0"}, port=8080, comment="Det virker ikke for 16134",
    )

    for leaked in ("16134", "15831", "selfservice-login", "hemmeligt-kodeord", "kalendertoken",
                   "pushemne", "mitdomaene", "daniels-mac", "/Users/daniel"):
        assert leaked not in report, leaked
    assert "Version: 1.17.0 (commit abc1234)" in report
    assert "Antal profiler: 2" in report
    assert "[profil=Profil 2, duration_seconds=0.2]" in report  # 16134 sorteres efter 15831
    assert "Executable doesn't exist" in report
    assert "Brugerens beskrivelse:" in report


def test_send_error_report_posts_to_report_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERMATE_TELEMETRY_URL", "https://example.invalid/telemetry/heartbeat.php")
    monkeypatch.setenv("ROSTERMATE_TELEMETRY_KEY", "ingest")
    client = TelemetryClient(tmp_path, tmp_path, "1.17.0")
    client.set_enabled(False)
    calls = []

    class Response:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"id": 7}

    monkeypatch.setattr("telemetry.requests.post", lambda url, **kw: calls.append((url, kw)) or Response())

    assert client.send_error_report("rapport") == "7"
    url, kwargs = calls[0]
    assert url == "https://example.invalid/telemetry/report.php"
    assert kwargs["json"]["installation_id"] == ""  # statistik slået fra -> intet installations-ID
    assert kwargs["json"]["report"] == "rapport"


def test_send_error_report_explains_rate_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERMATE_TELEMETRY_URL", "https://example.invalid/heartbeat.php")
    monkeypatch.setenv("ROSTERMATE_TELEMETRY_KEY", "ingest")

    class Response:
        status_code = 429

    monkeypatch.setattr("telemetry.requests.post", lambda *_a, **_k: Response())
    try:
        TelemetryClient(tmp_path, tmp_path, "1").send_error_report("x")
    except RuntimeError as exc:
        assert "i morgen" in str(exc)
    else:
        raise AssertionError("forventede RuntimeError")


def test_report_problem_page_previews_and_sends(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_module, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(app_module, "ERROR_LOG_PATH", tmp_path / "errors.jsonl")
    app_module.save_driver_settings("16134", {"wizard_completed": True})
    app_module.record_error(app_module.ERROR_LOG_PATH, "manual-sync", "boom", {"driver_id": "16134"})
    sent = []
    monkeypatch.setattr(TelemetryClient, "send_error_report", lambda self, report: sent.append(report) or "12")
    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        page = client.get("/16134/report-problem").get_data(as_text=True)
        response = client.post("/16134/report-problem", data={"comment": "hjælp"})

    assert "Det her bliver sendt" in page and "boom" in page
    assert response.status_code == 200 and "Rapportnummer: 12" in response.get_json()["message"]
    assert "16134" not in sent[0] and "hjælp" in sent[0]


def test_admin_report_page_is_hidden_without_admin_key(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "BASE_DIR", tmp_path)
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        assert client.get("/1234/admin/reports/1").status_code == 404
