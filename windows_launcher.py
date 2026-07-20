from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

from port_config import configured_port, ensure_available_port


PROJECT_DIR = Path(__file__).resolve().parent
DATA_ROOT = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "RosterMate"
LOG_DIR = DATA_ROOT / "logs"
LAUNCHER_LOG = LOG_DIR / "launcher.log"


def log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with LAUNCHER_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")


def health(port: int) -> dict[str, object] | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
            return json.load(response)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def current_version() -> str:
    result = subprocess.run(
        [sys.executable, "-c", "import app; print(app.APP_VERSION)"],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def listener_pid(port: int) -> int:
    result = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        capture_output=True,
        text=True,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    suffix = f":{port}"
    for line in result.stdout.splitlines():
        columns = line.split()
        if len(columns) >= 5 and columns[1].endswith(suffix) and columns[3].upper() == "LISTENING":
            try:
                return int(columns[4])
            except ValueError:
                continue
    return 0


def start_tray(server_pid: int) -> None:
    if os.environ.get("ROSTERMATE_NO_TRAY") == "1":
        return
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    subprocess.Popen(
        [str(pythonw), "tray.py", "--server-pid", str(server_pid)],
        cwd=PROJECT_DIR,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    log(f"Tray-ikon startet for serverproces {server_pid}.")


def open_wizard(port: int) -> None:
    url = f"http://localhost:{port}/wizard/"
    if os.environ.get("ROSTERMATE_NO_BROWSER") != "1":
        os.startfile(url)  # type: ignore[attr-defined]
    log(f"Wizard klar på {url}")


def launch() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    expected = current_version()
    port = configured_port()
    existing_health = health(port)
    if existing_health and existing_health.get("version") == expected:
        start_tray(listener_pid(port))
        open_wizard(port)
        return 0

    update = subprocess.run([sys.executable, "auto_update.py"], cwd=PROJECT_DIR, check=False)
    log(f"Opdateringskontrol afsluttet med kode {update.returncode}.")
    expected = current_version()
    port = ensure_available_port()
    os.environ["ROSTERMATE_PORT"] = str(port)

    stdout_log = (LOG_DIR / "rostermate.stdout.log").open("a", encoding="utf-8")
    stderr_log = (LOG_DIR / "rostermate.stderr.log").open("a", encoding="utf-8")
    server = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=PROJECT_DIR,
        env=os.environ.copy(),
        stdout=stdout_log,
        stderr=stderr_log,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    log(f"Serverproces {server.pid} startet på port {port}.")

    for _ in range(60):
        if server.poll() is not None:
            raise RuntimeError(f"Serveren stoppede med kode {server.returncode}. Se rostermate.stderr.log.")
        status = health(port)
        if status and status.get("version") == expected:
            start_tray(server.pid)
            open_wizard(port)
            return 0
        time.sleep(0.5)
    raise RuntimeError(f"RosterMate svarede ikke på port {port} inden for 30 sekunder.")


def main() -> int:
    try:
        return launch()
    except Exception as exc:
        log(f"STARTFEJL: {exc}\n{traceback.format_exc()}")
        print(f"RosterMate kunne ikke starte: {exc}", file=sys.stderr)
        print(f"Se loggen: {LAUNCHER_LOG}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
