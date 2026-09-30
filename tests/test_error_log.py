from pathlib import Path

from error_log import MAX_LOG_BYTES, classify_error, read_recent_errors, record_error, sanitize_error_message, split_recent_entries


def test_classify_error_returns_actionable_categories():
    assert classify_error("Bad CPU type in executable") == "runtime-arkitektur"
    assert classify_error("SelfService-sessionen er udløbet") == "session-udløbet"
    assert classify_error("Page.wait_for_function: Timeout") == "timeout"


def test_dashboard_log_split_keeps_success_timings_out_of_errors():
    errors, timings = split_recent_entries([
        {"component": "sync-timing", "event_type": "diagnostic"},
        {"component": "manual-sync", "message": "timeout"},
    ])

    assert [entry["component"] for entry in errors] == ["manual-sync"]
    assert [entry["component"] for entry in timings] == ["sync-timing"]


def test_sanitize_error_message_redacts_secrets_and_urls():
    message = "POST https://user:password@example.test/login?token=secret-pass failed password=another-secret"

    sanitized = sanitize_error_message(message)

    assert "password" in sanitized
    assert "secret-pass" not in sanitized
    assert "another-secret" not in sanitized
    assert "user:password@" not in sanitized


def test_record_and_read_recent_errors_are_newest_first(tmp_path: Path):
    path = tmp_path / "logs" / "errors.jsonl"

    record_error(path, "manual-sync", RuntimeError("første fejl"), {"driver_id": "1234"})
    record_error(path, "automatic-sync", "anden fejl")

    entries = read_recent_errors(path)

    assert [entry["component"] for entry in entries] == ["automatic-sync", "manual-sync"]
    assert entries[1]["context"] == {"driver_id": "1234"}
    assert entries[1]["category"] == "ukendt"


def test_error_log_rotates_before_growing_without_bound(tmp_path: Path):
    path = tmp_path / "errors.jsonl"
    path.write_bytes(b"x" * (MAX_LOG_BYTES + 1))

    record_error(path, "sync", "ny fejl")

    assert path.with_suffix(".jsonl.1").exists()
    assert len(read_recent_errors(path)) == 1
