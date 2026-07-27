from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent


def installed_user_data_root(project_dir: Path = PROJECT_DIR) -> Path:
    """Resolve the owning user's data directory even when launched by a service."""
    try:
        local_app_data = project_dir.parents[1]
        if project_dir.parent.name.lower() == "programs" and local_app_data.name.lower() == "local":
            return local_app_data / "RosterMate"
    except IndexError:
        pass
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "RosterMate"


DATA_ROOT = installed_user_data_root()
os.environ["ROSTERMATE_HOME"] = str(DATA_ROOT)

from port_config import configured_port, ensure_available_port


LOG_DIR = DATA_ROOT / "logs"
LAUNCHER_LOG = LOG_DIR / "launcher.log"
STARTUP_TIMEOUT_SECONDS = 120


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


def log_tail(path: Path, lines: int = 20) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(content[-lines:]).strip()


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
    tray_stdout = (LOG_DIR / "tray.stdout.log").open("a", encoding="utf-8")
    tray_stderr = (LOG_DIR / "tray.stderr.log").open("a", encoding="utf-8")
    subprocess.Popen(
        [str(pythonw), "tray.py", "--server-pid", str(server_pid)],
        cwd=PROJECT_DIR,
        env=os.environ.copy(),
        stdout=tray_stdout,
        stderr=tray_stderr,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    log(f"Tray-ikon startet for serverproces {server_pid}.")


def open_roster_mate(port: int) -> None:
    url = f"http://localhost:{port}/"
    if os.environ.get("ROSTERMATE_NO_BROWSER") != "1":
        os.startfile(url)  # type: ignore[attr-defined]
    log(f"RosterMate klar på {url}")


def launch() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    expected = current_version()
    port = configured_port()
    existing_health = health(port)
    if existing_health and existing_health.get("version") == expected:
        start_tray(listener_pid(port))
        open_roster_mate(port)
        return 0

    update = subprocess.run(
        [sys.executable, "auto_update.py"],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    update_message = (update.stdout or update.stderr).strip()
    if update_message:
        log(update_message)
    log(f"Opdateringskontrol afsluttet med kode {update.returncode}.")
    expected = current_version()
    port = ensure_available_port()
    os.environ["ROSTERMATE_PORT"] = str(port)

    stdout_path = LOG_DIR / "rostermate.stdout.log"
    stderr_path = LOG_DIR / "rostermate.stderr.log"
    stdout_log = stdout_path.open("a", encoding="utf-8")
    stderr_log = stderr_path.open("a", encoding="utf-8")
    server_environment = os.environ.copy()
    server_environment["PYTHONUNBUFFERED"] = "1"
    server = subprocess.Popen(
        [sys.executable, "-u", "app.py"],
        cwd=PROJECT_DIR,
        env=server_environment,
        stdout=stdout_log,
        stderr=stderr_log,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    log(f"Serverproces {server.pid} startet på port {port}.")

    attempts = STARTUP_TIMEOUT_SECONDS * 2
    for attempt in range(attempts):
        if server.poll() is not None:
            details = log_tail(stderr_path)
            suffix = f"\nSeneste serverfejl:\n{details}" if details else ""
            raise RuntimeError(f"Serveren stoppede med kode {server.returncode}.{suffix}")
        status = health(port)
        if status and status.get("version") == expected:
            start_tray(server.pid)
            open_roster_mate(port)
            return 0
        if status and status.get("version") != expected:
            log(f"Port {port} svarede med en anden RosterMate-version: {status.get('version')!r}.")
        if attempt and attempt % 20 == 0:
            log(f"Venter stadig på serverproces {server.pid} på port {port} ({attempt // 2} sekunder).")
        time.sleep(0.5)
    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()
    details = log_tail(stderr_path)
    suffix = f"\nSeneste serverlog:\n{details}" if details else ""
    raise RuntimeError(
        f"RosterMate svarede ikke på port {port} inden for {STARTUP_TIMEOUT_SECONDS} sekunder.{suffix}"
    )


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
