from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from release_update import CHECK_INTERVAL_SECONDS, check_for_release_update


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

    result = check_for_release_update(
        cache_path,
        "1.8.0",
        platform_name="darwin",
        now=1001,
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must use cache")),
    )

    assert result["available"] is False
    assert result["current_version"] == "1.8.0"
