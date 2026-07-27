from __future__ import annotations

import subprocess
import sys
from typing import Any


SERVICE_NAME = "RosterMate SelfService"


def _keyring() -> Any:
    import keyring

    return keyring


def get_password(driver_id: str) -> str:
    if sys.platform == "darwin":
        result = subprocess.run(
            ["security", "find-generic-password", "-s", SERVICE_NAME, "-a", driver_id, "-w"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    try:
        return str(_keyring().get_password(SERVICE_NAME, driver_id) or "")
    except Exception:
        return ""


def set_password(driver_id: str, password: str) -> None:
    if not password:
        return
    if sys.platform == "darwin":
        subprocess.run(
            ["security", "add-generic-password", "-U", "-s", SERVICE_NAME, "-a", driver_id, "-w", password],
            capture_output=True,
            text=True,
            check=True,
        )
        return
    _keyring().set_password(SERVICE_NAME, driver_id, password)


def delete_password(driver_id: str) -> None:
    if sys.platform == "darwin":
        subprocess.run(
            ["security", "delete-generic-password", "-s", SERVICE_NAME, "-a", driver_id],
            capture_output=True,
            check=False,
        )
        return
    try:
        _keyring().delete_password(SERVICE_NAME, driver_id)
    except Exception:
        pass
