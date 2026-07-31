from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from release_update import CHECK_INTERVAL_SECONDS, check_for_release_update
import app as app_module


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def github_release_opener(_request, **_kwargs):
    payload = {
        "tag_name": "v1.8.0",
        "html_url": "https://github.com/Danish-Busdriver/rostermate/releases/tag/v1.8.0",
        "assets": [
            {
                "name": "RosterMate-1.8.0-macOS.pkg",
                "browser_download_url": "https://github.com/Danish-Busdriver/rostermate/releases/download/v1.8.0/RosterMate-1.8.0-macOS.pkg",
            },
            {
                "name": "RosterMate-1.8.0-Windows-Setup.exe",
                "browser_download_url": "https://github.com/Danish-Busdriver/rostermate/releases/download/v1.8.0/RosterMate-1.8.0-Windows-Setup.exe",
            },
        ],
    }
    return Response(json.dumps(payload).encode())


def test_daily_release_check_selects_platform_installer(tmp_path):
    cache_path = tmp_path / "release-update.json"

    mac = check_for_release_update(
        cache_path,
        "1.7.3",
        platform_name="darwin",
        now=1000,
        opener=github_release_opener,
    )

    assert mac["available"] is True
    assert mac["latest_version"] == "1.8.0"
    assert mac["download_url"].endswith("RosterMate-1.8.0-macOS.pkg")


def test_fresh_cache_prevents_another_github_request(tmp_path):
    cache_path = tmp_path / "release-update.json"
    check_for_release_update(
        cache_path,
        "1.7.3",
        platform_name="darwin",
        now=1000,
        opener=github_release_opener,
    )

    def unexpected_request(*_args, **_kwargs):
        raise AssertionError("GitHub must not be checked more than once per day")

    cached = check_for_release_update(
        cache_path,
        "1.7.3",
        now=1000 + CHECK_INTERVAL_SECONDS - 1,
        opener=unexpected_request,
    )

    assert cached["latest_version"] == "1.8.0"


def test_offline_check_preserves_last_known_update(tmp_path):
    cache_path = tmp_path / "release-update.json"
    check_for_release_update(
        cache_path,
        "1.7.3",
        platform_name="darwin",
        now=1000,
        opener=github_release_opener,
    )

    def offline(*_args, **_kwargs):
        raise OSError("offline")

    result = check_for_release_update(
        cache_path,
        "1.7.3",
        platform_name="darwin",
        now=1000 + CHECK_INTERVAL_SECONDS,
        opener=offline,
    )

    assert result["available"] is True
    assert result["download_url"].endswith("macOS.pkg")
    assert result["error"] == "offline"


def test_current_release_does_not_show_update(tmp_path):
    result = check_for_release_update(
        tmp_path / "release-update.json",
        "1.8.0",
        platform_name="win32",
        now=1000,
        opener=github_release_opener,
    )

    assert result["available"] is False
    assert result["download_url"].endswith("RosterMate-1.8.0-Windows-Setup.exe")


def test_fresh_cache_stops_showing_release_after_app_was_updated(tmp_path):
    cache_path = tmp_path / "release-update.json"
    check_for_release_update(
        cache_path,
        "1.7.3",
        platform_name="darwin",
        now=1000,
        opener=github_release_opener,
    )

    requests = []
    result = check_for_release_update(
        cache_path,
        "1.8.0",
        platform_name="darwin",
        now=1001,
        opener=lambda *args, **kwargs: requests.append((args, kwargs)) or github_release_opener(*args, **kwargs),
    )

    assert result["available"] is False
    assert result["current_version"] == "1.8.0"
    assert len(requests) == 1


def test_changed_installed_version_forces_a_fresh_release_check(tmp_path):
    cache_path = tmp_path / "release-update.json"
    check_for_release_update(
        cache_path,
        "1.8.0",
        platform_name="darwin",
        now=1000,
        opener=github_release_opener,
    )
    requests = []

    result = check_for_release_update(
        cache_path,
        "1.7.9",
        platform_name="darwin",
        now=1001,
        opener=lambda *args, **kwargs: requests.append((args, kwargs)) or github_release_opener(*args, **kwargs),
    )

    assert result["available"] is True
    assert result["latest_version"] == "1.8.0"
    assert len(requests) == 1


def test_install_update_route_downloads_and_launches_selected_asset(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(app_module, "check_for_release_update", lambda *_args, **_kwargs: {
        "available": True,
        "latest_version": "1.14.0",
        "download_url": "https://github.com/Danish-Busdriver/rostermate/releases/download/v1.14.0/RosterMate-1.14.0-macOS.pkg",
    })
    calls = []
    monkeypatch.setattr(
        app_module,
        "download_and_launch_installer",
        lambda url, version, destination: calls.append((url, version, destination)) or SimpleNamespace(message="Installer åbnet"),
    )
    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        response = client.post("/1234/install-update")

    assert response.status_code == 200
    assert response.get_json()["message"] == "Installer åbnet"
    assert calls[0][1:] == ("1.14.0", tmp_path / "updates")


def test_install_update_route_refuses_when_current(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(app_module, "check_for_release_update", lambda *_args, **_kwargs: {"available": False})
    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        response = client.post("/1234/install-update")

    assert response.status_code == 409
    assert "ingen nyere" in response.get_json()["message"]
