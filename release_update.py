from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import certifi


LATEST_RELEASE_API = "https://api.github.com/repos/Danish-Busdriver/rostermate/releases/latest"
CHECK_INTERVAL_SECONDS = 24 * 60 * 60
Opener = Callable[..., Any]


def _verified_urlopen(request: urllib.request.Request, *, timeout: int) -> Any:
    context = ssl.create_default_context(cafile=certifi.where())
    return urllib.request.urlopen(request, timeout=timeout, context=context)


def _version_tuple(value: str) -> tuple[int, ...]:
    normalized = value.strip().lower().removeprefix("v")
    parts = normalized.split(".")
    if not parts or any(not part.isdigit() for part in parts):
        return ()
    return tuple(int(part) for part in parts)


def _safe_https_url(value: Any) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    return url if parsed.scheme == "https" and parsed.netloc else ""


def _load_cache(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _download_url(assets: list[Any], platform_name: str, fallback_url: str) -> str:
    expected_suffix = ".pkg" if platform_name == "darwin" else "-Windows-Setup.exe"
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        if name.endswith(expected_suffix):
            url = _safe_https_url(asset.get("browser_download_url"))
            if url:
                return url
    return fallback_url


def _is_newer(latest_version: str, current_version: str) -> bool:
    latest = _version_tuple(latest_version)
    current = _version_tuple(current_version)
    return bool(latest and current and latest > current)


def check_for_release_update(
    cache_path: Path,
    current_version: str,
    *,
    platform_name: str | None = None,
    now: float | None = None,
    opener: Opener = _verified_urlopen,
) -> dict[str, Any]:
    """Check GitHub at most daily and return a platform-specific update status."""
    current_time = time.time() if now is None else now
    active_platform = platform_name or sys.platform
    cached = _load_cache(cache_path)
    checked_at = float(cached.get("checked_at") or 0)
    cached_current_version = str(cached.get("current_version") or "")
    if (
        checked_at
        and cached_current_version == current_version
        and current_time - checked_at < CHECK_INTERVAL_SECONDS
    ):
        cached["current_version"] = current_version
        cached["available"] = _is_newer(str(cached.get("latest_version") or ""), current_version)
        _save_cache(cache_path, cached)
        return cached

    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"RosterMate/{current_version}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with opener(request, timeout=4) as response:
            release = json.load(response)
        if not isinstance(release, dict):
            raise ValueError("GitHub returnerede et ugyldigt release-svar")
        latest_version = str(release.get("tag_name") or "").removeprefix("v")
        release_url = _safe_https_url(release.get("html_url"))
        assets = release.get("assets") if isinstance(release.get("assets"), list) else []
        available = _is_newer(latest_version, current_version)
        result = {
            "checked_at": current_time,
            "current_version": current_version,
            "latest_version": latest_version,
            "available": available,
            "download_url": _download_url(assets, active_platform, release_url),
            "release_url": release_url,
            "platform": active_platform,
            "error": "",
        }
    except Exception as exc:
        result = {
            **cached,
            "checked_at": current_time,
            "current_version": current_version,
            "available": bool(cached.get("available", False)),
            "error": str(exc),
        }

    _save_cache(cache_path, result)
    return result
