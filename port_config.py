from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path


DEFAULT_PORT = 8080
MIN_PORT = 1024
MAX_PORT = 65535


def storage_root(platform_name: str | None = None) -> Path:
    configured = os.environ.get("ROSTERMATE_HOME", "").strip()
    if configured:
        return Path(configured).expanduser()
    if (platform_name or sys.platform) == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "RosterMate"
    return Path(__file__).resolve().parent


def config_path(platform_name: str | None = None, root: Path | None = None) -> Path:
    return (root or storage_root(platform_name)) / "data" / "app-config.json"


def valid_port(value: object) -> int | None:
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return port if MIN_PORT <= port <= MAX_PORT else None


def configured_port(platform_name: str | None = None, root: Path | None = None) -> int:
    environment_port = valid_port(os.environ.get("ROSTERMATE_PORT"))
    if environment_port:
        return environment_port
    try:
        payload = json.loads(config_path(platform_name, root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_PORT
    return valid_port(payload.get("port")) or DEFAULT_PORT


def save_port(port: int, platform_name: str | None = None, root: Path | None = None) -> int:
    checked = valid_port(port)
    if checked is None:
        raise ValueError(f"Porten skal være mellem {MIN_PORT} og {MAX_PORT}")
    path = config_path(platform_name, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"port": checked}, indent=2) + "\n", encoding="utf-8")
    return checked


def port_is_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            connection.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def ensure_available_port() -> int:
    selected = configured_port()
    if port_is_available(selected):
        return save_port(selected)
    for candidate in range(DEFAULT_PORT, DEFAULT_PORT + 100):
        if port_is_available(candidate):
            return save_port(candidate)
    raise RuntimeError("RosterMate kunne ikke finde en ledig port mellem 8080 og 8179")


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "configured"
    if command == "configured":
        print(configured_port())
        return 0
    if command == "ensure":
        print(ensure_available_port())
        return 0
    raise SystemExit(f"Ukendt kommando: {command}")


if __name__ == "__main__":
    raise SystemExit(main())
