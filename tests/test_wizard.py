from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
import launch_agent as launch_agent_module
from login import read_stable_page_content


class NavigatingPage:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.load_waits = 0

    def content(self) -> str:
        if self.failures:
            self.failures -= 1
            raise RuntimeError("Page.content: Unable to retrieve content because the page is navigating and changing the content.")
        return "<html>Assignments</html>"

    def wait_for_load_state(self, *_args, **_kwargs) -> None:
        self.load_waits += 1

    def wait_for_timeout(self, _milliseconds: int) -> None:
        pass


def test_read_stable_page_content_retries_during_navigation():
    page = NavigatingPage(failures=2)

    html = read_stable_page_content(page)

    assert html == "<html>Assignments</html>"
    assert page.load_waits == 2


def test_read_stable_page_content_returns_none_when_navigation_does_not_settle():
    page = NavigatingPage(failures=10)

    assert read_stable_page_content(page, attempts=3) is None


def test_read_stable_page_content_reraises_non_navigation_errors():
    class BrokenPage(NavigatingPage):
        def content(self) -> str:
            raise RuntimeError("Browser process closed")

    try:
        read_stable_page_content(BrokenPage(failures=0))
    except RuntimeError as exc:
        assert str(exc) == "Browser process closed"
    else:
        raise AssertionError("Expected the non-navigation error to be re-raised")


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
