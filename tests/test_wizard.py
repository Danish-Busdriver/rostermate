import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
import launch_agent as launch_agent_module
from login import (
    AUTHENTICATED_MARKER_SELECTOR,
    LOGIN_FIELD_SELECTOR,
    detect_selfservice_login_state,
    launch_authenticated_context,
    prefill_selfservice_credentials,
    read_stable_page_content,
    restore_saved_cookies,
    restore_session_storage,
    save_session_storage,
)
from session_store import SelfServiceSessionStore


def test_health_reports_current_app_version():
    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "version": app_module.APP_VERSION}


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


class MarkerLocator:
    def __init__(self, count: int) -> None:
        self._count = count

    def count(self) -> int:
        return self._count


class LoginMarkerPage:
    def __init__(self, url: str, *, login_fields: int = 0, authenticated_markers: int = 0) -> None:
        self.url = url
        self.login_fields = login_fields
        self.authenticated_markers = authenticated_markers

    def locator(self, selector: str) -> MarkerLocator:
        if "Username" in selector:
            return MarkerLocator(self.login_fields)
        return MarkerLocator(self.authenticated_markers)

    def content(self) -> str:
        raise AssertionError("Login detection must not read the complete page HTML")


def test_login_detection_uses_only_url_and_small_dom_markers():
    assert detect_selfservice_login_state(LoginMarkerPage("https://example/Account/Login", login_fields=2)) == "login"
    assert detect_selfservice_login_state(LoginMarkerPage("https://example/Assignments")) == "unknown"
    assert detect_selfservice_login_state(LoginMarkerPage("https://example/home", authenticated_markers=1)) == "authenticated"
    assert detect_selfservice_login_state(LoginMarkerPage("https://example/loading")) == "unknown"


def test_login_detection_ignores_hidden_legacy_dom_elements():
    assert "Username:visible" in LOGIN_FIELD_SELECTOR
    assert "Password:visible" in LOGIN_FIELD_SELECTOR
    assert "#Calendar:visible" in AUTHENTICATED_MARKER_SELECTOR


def test_prefill_credentials_fills_visible_fields_without_submitting():
    filled: list[str] = []

    class Locator:
        @property
        def first(self):
            return self

        def count(self):
            return 1

        def fill(self, value):
            filled.append(value)

    class Page:
        def locator(self, _selector):
            return Locator()

    prefill_selfservice_credentials(Page(), "driver", "secret")

    assert filled == ["driver", "secret"]


def test_launch_authenticated_context_reuses_persistent_driver_profile(tmp_path):
    calls: list[tuple[str, object]] = []

    class Context:
        def add_init_script(self, **kwargs):
            calls.append(("init-script", kwargs))

    context = Context()

    class Chromium:
        def launch_persistent_context(self, **kwargs):
            calls.append(("persistent", kwargs))
            return context

        def launch(self, **kwargs):
            calls.append(("browser", kwargs))
            raise AssertionError("A separate browser must not be launched")

    class Playwright:
        chromium = Chromium()

    store = SelfServiceSessionStore("12345", tmp_path / "state.json", tmp_path / "profile")
    store.user_data_dir.mkdir()

    browser, context = launch_authenticated_context(Playwright(), store, headless=True)

    assert browser is None
    assert context is not None
    assert calls == [("persistent", {"user_data_dir": str(store.user_data_dir), "headless": True})]


def test_launch_authenticated_context_prefers_persistent_profile_over_exported_state(tmp_path):
    calls: list[tuple[str, object]] = []

    class Context:
        def add_init_script(self, **kwargs):
            calls.append(("init-script", kwargs))

    context = Context()

    class Chromium:
        def launch(self, **kwargs):
            raise AssertionError("A separate browser must not be launched")

        def launch_persistent_context(self, **kwargs):
            calls.append(("persistent", kwargs))
            return context

    class Playwright:
        chromium = Chromium()

    store = SelfServiceSessionStore("12345", tmp_path / "state.json", tmp_path / "profile")
    store.storage_state_path.write_text('{"cookies":[]}', encoding="utf-8")
    store.user_data_dir.mkdir()

    browser, restored_context = launch_authenticated_context(Playwright(), store, headless=True)

    assert browser is None
    assert restored_context is context
    assert calls == [
        ("persistent", {"user_data_dir": str(store.user_data_dir), "headless": True}),
    ]


def test_hidden_headful_context_is_positioned_offscreen(tmp_path):
    calls = []

    class Context:
        pass

    class Chromium:
        def launch_persistent_context(self, **kwargs):
            calls.append(kwargs)
            return Context()

    class Playwright:
        chromium = Chromium()

    store = SelfServiceSessionStore("12345", tmp_path / "state.json", tmp_path / "profile")
    store.user_data_dir.mkdir()

    launch_authenticated_context(
        Playwright(),
        store,
        headless=False,
        hide_window=True,
    )

    assert calls == [{
        "user_data_dir": str(store.user_data_dir),
        "headless": False,
        "args": ["--window-position=-32000,-32000", "--start-minimized"],
    }]


def test_session_storage_is_saved_and_restored(tmp_path):
    store = SelfServiceSessionStore("12345", tmp_path / "state.json", tmp_path / "profile")

    class Page:
        def evaluate(self, _script):
            return {"origin": "https://selfservice.example", "items": {"auth": "token"}}

    scripts: list[str] = []

    class Context:
        def add_init_script(self, *, script):
            scripts.append(script)

    save_session_storage(Page(), store)
    restore_session_storage(Context(), store)

    saved = store.session_storage_state_path.read_text(encoding="utf-8")
    assert '"auth": "token"' in saved
    assert len(scripts) == 1
    assert "window.sessionStorage.setItem" in scripts[0]
    assert "https://selfservice.example" in scripts[0]


def test_saved_session_cookies_are_restored_into_persistent_context(tmp_path):
    store = SelfServiceSessionStore("12345", tmp_path / "state.json", tmp_path / "profile")
    cookies = [{"name": "session", "value": "token", "domain": "selfservice.example", "path": "/"}]
    store.storage_state_path.write_text(json.dumps({"cookies": cookies}), encoding="utf-8")
    restored: list[list[dict[str, str]]] = []

    class Context:
        def add_cookies(self, items):
            restored.append(items)

    restore_saved_cookies(Context(), store)

    assert restored == [cookies]


def test_clear_removes_session_storage_state(tmp_path):
    store = SelfServiceSessionStore("12345", tmp_path / "state.json", tmp_path / "profile")
    store.storage_state_path.write_text("{}", encoding="utf-8")
    store.session_storage_state_path.write_text("{}", encoding="utf-8")
    store.user_data_dir.mkdir()

    store.clear()

    assert not store.storage_state_path.exists()
    assert not store.session_storage_state_path.exists()
    assert not store.user_data_dir.exists()


def test_clear_browser_profile_preserves_exported_session(tmp_path):
    store = SelfServiceSessionStore("12345", tmp_path / "state.json", tmp_path / "profile")
    store.storage_state_path.write_text('{"cookies":[]}', encoding="utf-8")
    store.session_storage_state_path.write_text('{"origin":"https://selfservice.example"}', encoding="utf-8")
    store.user_data_dir.mkdir()
    (store.user_data_dir / "Preferences").write_text("{}", encoding="utf-8")

    store.clear_browser_profile()

    assert not store.user_data_dir.exists()
    assert store.storage_state_path.exists()
    assert store.session_storage_state_path.exists()


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


def test_first_run_wizard_contains_background_login_and_secure_fallback():
    from wizard import FIRST_RUN_TEMPLATE

    assert 'id="selfservice-user"' in FIRST_RUN_TEMPLATE
    assert 'id="selfservice-password"' in FIRST_RUN_TEMPLATE
    assert "Log ind og test forbindelse" in FIRST_RUN_TEMPLATE
    assert "Åbn loginvindue i stedet" in FIRST_RUN_TEMPLATE
    assert "{{ platform_labels.credential_store }}" in FIRST_RUN_TEMPLATE


def test_home_redirects_to_the_only_configured_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_module, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "output")
    profile_dir = app_module.DATA_DIR / "12345"
    profile_dir.mkdir(parents=True)
    (profile_dir / "settings.json").write_text('{"wizard_completed": false}', encoding="utf-8")

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        response = client.get("/", follow_redirects=False)
        chooser = client.get("/?choose=1")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/12345/wizard")
    assert chooser.status_code == 200
    assert b"Tilf\xc3\xb8j profil" in chooser.data


def test_global_wizard_address_opens_profile_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_module, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "output")
    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        response = client.get("/wizard/")

    assert response.status_code == 200
    assert b"V\xc3\xa6lg chauff\xc3\xb8rnummer" in response.data


def test_relogin_url_opens_login_controls_for_completed_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_module, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "output")
    paths = app_module.get_driver_paths("1234")
    app_module.save_driver_settings(
        "1234",
        {
            "wizard_completed": True,
            "selfservice_session_verified": False,
            "user": "tester",
        },
    )
    paths["selfservice_storage_state_path"].write_text('{"cookies":[]}', encoding="utf-8")
    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        response = client.get("/1234/wizard?relogin=1")

    assert response.status_code == 200
    assert b"Log ind og test forbindelse" in response.data
    assert b"\xc3\x85bn loginvindue i stedet" in response.data


def test_settings_page_contains_installation_port(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_module, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "output")
    app_module.save_driver_settings("1234", {"wizard_completed": True})
    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        response = client.get("/1234/settings-page")

    assert response.status_code == 200
    assert b"Lokal server" in response.data
    assert b'name="app_port"' in response.data
    assert b"dagligt mellem kl. 12 og 14" in response.data
    assert "Timelønnet (dagligt mellem kl. 9 og 16)".encode() in response.data
    assert "faste, tilfældigt valgte tider".encode() in response.data
    assert b'name="automatic_sync_enabled"' in response.data
    assert b'name="notify_on_changes"' in response.data
    assert "Vis en systembesked, når vagter ændres".encode() in response.data
    assert b"run_every_minutes" not in response.data
    assert b"Google Calendar" not in response.data


def test_settings_can_change_installation_port(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_module, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(app_module, "port_is_available", lambda port: port == 8092)
    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        response = client.post("/1234/settings", data={
            "app_port": "8092",
            "automatic_sync_enabled": "true",
            "notify_on_changes": "true",
        })

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["restart_required"] is True
    assert payload["next_url"] == "http://localhost:8092/"
    assert payload["automatic_sync_enabled"] is True
    assert payload["notify_on_changes"] is True
    assert json.loads((tmp_path / "data" / "app-config.json").read_text(encoding="utf-8")) == {"port": 8092}


def test_wizard_complete_creates_launch_agent_when_enabled(tmp_path, monkeypatch):
    # This test specifically verifies the macOS LaunchAgent adapter. Windows
    # startup behavior is covered separately in test_platform.py.
    monkeypatch.setattr(launch_agent_module.sys, "platform", "darwin")
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


def test_wizard_complete_does_not_restart_running_server(tmp_path, monkeypatch):
    monkeypatch.setattr(launch_agent_module.sys, "platform", "darwin")
    monkeypatch.setattr(app_module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_module, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(
        launch_agent_module,
        "launch_agent_path",
        lambda driver_id, home_dir=None: tmp_path / "LaunchAgents" / f"{driver_id}.plist",
    )
    launchctl_calls = []
    monkeypatch.setattr(launch_agent_module, "_run_launchctl", launchctl_calls.append)

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        response = client.post(
            "/1234/wizard/complete",
            data={"launch_at_login": "true"},
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/1234/")
    assert launchctl_calls == []


def test_wizard_complete_removes_launch_agent_when_disabled(tmp_path, monkeypatch):
    # This test specifically verifies the macOS LaunchAgent adapter. Windows
    # startup behavior is covered separately in test_platform.py.
    monkeypatch.setattr(launch_agent_module.sys, "platform", "darwin")
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
