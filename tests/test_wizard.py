from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
import launch_agent as launch_agent_module


def test_wizard_test_connection_route_returns_error_without_session(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_module, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "output")

    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        response = client.post("/1234/wizard/test-connection")

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"


def test_wizard_complete_creates_launch_agent_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_module, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(launch_agent_module, "Path", Path)
    monkeypatch.setattr(launch_agent_module, "_run_launchctl", lambda command: None)
    monkeypatch.setattr(launch_agent_module, "launch_agent_path", lambda driver_id, home_dir=None: (tmp_path / "LaunchAgents" / f"{driver_id}.plist"))

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
    launch_agent_path = tmp_path / "LaunchAgents" / "1234.plist"
    assert launch_agent_path.exists()


def test_wizard_complete_removes_launch_agent_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_module, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(launch_agent_module, "_run_launchctl", lambda command: None)
    monkeypatch.setattr(launch_agent_module, "launch_agent_path", lambda driver_id, home_dir=None: (tmp_path / "LaunchAgents" / f"{driver_id}.plist"))

    launch_agent_file = tmp_path / "LaunchAgents" / "1234.plist"
    launch_agent_file.parent.mkdir(parents=True, exist_ok=True)
    launch_agent_file.write_text("placeholder", encoding="utf-8")

    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        response = client.post(
            "/1234/wizard/complete",
            data={
                "calendar_name": "Min Vagtplan",
                "days_ahead": "14",
                "show_menu_bar_icon": "true",
                "notify_on_changes": "true",
            },
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert not launch_agent_file.exists()
