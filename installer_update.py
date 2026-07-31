from __future__ import annotations

import os
import re
import ssl
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import certifi


MAX_INSTALLER_BYTES = 500 * 1024 * 1024
Downloader = Callable[..., Any]
Runner = Callable[..., Any]


class InstallerUpdateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class InstallerUpdateResult:
    path: Path
    message: str


def _verified_urlopen(request: urllib.request.Request, *, timeout: int) -> Any:
    context = ssl.create_default_context(cafile=certifi.where())
    return urllib.request.urlopen(request, timeout=timeout, context=context)


def installer_filename(version: str, platform_name: str) -> str:
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(version)):
        raise InstallerUpdateError("Opdateringens versionsnummer er ugyldigt.")
    if platform_name == "darwin":
        return f"RosterMate-{version}-macOS.pkg"
    if platform_name == "win32":
        return f"RosterMate-{version}-Windows-Setup.exe"
    raise InstallerUpdateError("Automatisk installation understøttes kun på macOS og Windows.")


def validate_installer_url(url: str, version: str, platform_name: str) -> str:
    expected_name = installer_filename(version, platform_name)
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise InstallerUpdateError("Opdateringen kommer ikke fra den forventede GitHub-adresse.")
    if Path(parsed.path).name != expected_name:
        raise InstallerUpdateError("Opdateringsfilens navn passer ikke til den valgte version og platform.")
    return expected_name


def validate_installer_file(path: Path, platform_name: str) -> None:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            header = handle.read(4)
    except OSError as exc:
        raise InstallerUpdateError(f"Den hentede installationsfil kunne ikke læses: {exc}") from exc
    if size < 4 or size > MAX_INSTALLER_BYTES:
        raise InstallerUpdateError("Den hentede installationsfil har en ugyldig størrelse.")
    expected_header = b"xar!" if platform_name == "darwin" else b"MZ"
    if not header.startswith(expected_header):
        raise InstallerUpdateError("Den hentede fil er ikke en gyldig installationsfil til denne platform.")


def download_installer(
    url: str,
    version: str,
    destination_dir: Path,
    *,
    platform_name: str | None = None,
    opener: Downloader = _verified_urlopen,
) -> Path:
    active_platform = platform_name or sys.platform
    filename = validate_installer_url(url, version, active_platform)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / filename
    temporary = destination.with_suffix(destination.suffix + ".download")
    request = urllib.request.Request(url, headers={"User-Agent": f"RosterMate/{version}"})
    total = 0
    try:
        with opener(request, timeout=60) as response, temporary.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_INSTALLER_BYTES:
                    raise InstallerUpdateError("Opdateringsfilen er større end den tilladte grænse.")
                output.write(chunk)
        validate_installer_file(temporary, active_platform)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def launch_installer(
    path: Path,
    *,
    platform_name: str | None = None,
    runner: Runner = subprocess.Popen,
) -> None:
    active_platform = platform_name or sys.platform
    validate_installer_file(path, active_platform)
    if active_platform == "darwin":
        runner(["/usr/bin/open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    if active_platform == "win32":
        runner(
            [str(path)],
            cwd=path.parent,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        return
    raise InstallerUpdateError("Automatisk installation understøttes kun på macOS og Windows.")


def download_and_launch_installer(
    url: str,
    version: str,
    destination_dir: Path,
    *,
    platform_name: str | None = None,
    opener: Downloader = _verified_urlopen,
    runner: Runner = subprocess.Popen,
) -> InstallerUpdateResult:
    active_platform = platform_name or sys.platform
    path = download_installer(
        url,
        version,
        destination_dir,
        platform_name=active_platform,
        opener=opener,
    )
    launch_installer(path, platform_name=active_platform, runner=runner)
    platform_label = "macOS Installer" if active_platform == "darwin" else "Windows-installationsprogrammet"
    return InstallerUpdateResult(
        path=path,
        message=f"{platform_label} er åbnet. Følg trinnene dér for at færdiggøre opdateringen.",
    )
