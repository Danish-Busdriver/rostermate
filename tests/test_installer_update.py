from __future__ import annotations

import io
from pathlib import Path

import pytest

from installer_update import (
    InstallerUpdateError,
    download_and_launch_installer,
    download_installer,
    installer_filename,
    validate_installer_url,
)


class DownloadResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def opener_with(content: bytes):
    return lambda *_args, **_kwargs: DownloadResponse(content)


def test_platform_installer_names_are_version_specific():
    assert installer_filename("1.14.0", "darwin") == "RosterMate-1.14.0-macOS.pkg"
    assert installer_filename("1.14.0", "win32") == "RosterMate-1.14.0-Windows-Setup.exe"


def test_installer_url_must_be_exact_https_github_asset():
    valid = "https://github.com/Danish-Busdriver/rostermate/releases/download/v1.14.0/RosterMate-1.14.0-macOS.pkg"
    assert validate_installer_url(valid, "1.14.0", "darwin") == "RosterMate-1.14.0-macOS.pkg"

    with pytest.raises(InstallerUpdateError):
        validate_installer_url("https://example.com/RosterMate-1.14.0-macOS.pkg", "1.14.0", "darwin")
    with pytest.raises(InstallerUpdateError):
        validate_installer_url(valid, "1.14.1", "darwin")
    with pytest.raises(InstallerUpdateError):
        installer_filename("../danger", "darwin")


def test_download_validates_macos_package_and_uses_atomic_filename(tmp_path):
    url = "https://github.com/Danish-Busdriver/rostermate/releases/download/v1.14.0/RosterMate-1.14.0-macOS.pkg"
    path = download_installer(
        url,
        "1.14.0",
        tmp_path,
        platform_name="darwin",
        opener=opener_with(b"xar!test-package"),
    )

    assert path.name == "RosterMate-1.14.0-macOS.pkg"
    assert path.read_bytes() == b"xar!test-package"
    assert not path.with_suffix(".pkg.download").exists()


def test_download_rejects_invalid_installer_content(tmp_path):
    url = "https://github.com/Danish-Busdriver/rostermate/releases/download/v1.14.0/RosterMate-1.14.0-Windows-Setup.exe"

    with pytest.raises(InstallerUpdateError, match="ikke en gyldig"):
        download_installer(
            url,
            "1.14.0",
            tmp_path,
            platform_name="win32",
            opener=opener_with(b"not-an-exe"),
        )

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("platform_name", "content", "expected_command"),
    [("darwin", b"xar!pkg", "/usr/bin/open"), ("win32", b"MZexe", "RosterMate-1.14.0-Windows-Setup.exe")],
)
def test_download_and_launch_uses_native_platform_installer(tmp_path, platform_name, content, expected_command):
    filename = installer_filename("1.14.0", platform_name)
    url = f"https://github.com/Danish-Busdriver/rostermate/releases/download/v1.14.0/{filename}"
    calls = []

    result = download_and_launch_installer(
        url,
        "1.14.0",
        tmp_path,
        platform_name=platform_name,
        opener=opener_with(content),
        runner=lambda command, **kwargs: calls.append((command, kwargs)),
    )

    assert result.path.name == filename
    assert expected_command in calls[0][0][0]
