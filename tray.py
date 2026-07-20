from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from PIL import Image
import pystray


APP_URL = "http://127.0.0.1:8080"
PROJECT_DIR = Path(__file__).resolve().parent
ICON_PATH = PROJECT_DIR / "static" / "Rostermate.png"


def storage_root() -> Path:
    configured = os.environ.get("ROSTERMATE_HOME", "").strip()
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", PROJECT_DIR)) / "RosterMate"
    return PROJECT_DIR


def process_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def claim_single_instance(server_pid: int) -> Path | None:
    pid_path = storage_root() / "rostermate-tray.pid"
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        saved_parts = pid_path.read_text(encoding="utf-8").strip().split(",", 1)
        old_pid = int(saved_parts[0])
        old_server_pid = int(saved_parts[1]) if len(saved_parts) > 1 else 0
    except (OSError, ValueError):
        old_pid = 0
        old_server_pid = 0
    if old_pid and process_is_running(old_pid):
        if old_server_pid <= 0 or process_is_running(old_server_pid):
            return None
        for _ in range(10):
            time.sleep(0.5)
            if not process_is_running(old_pid):
                break
        if process_is_running(old_pid):
            return None
    pid_path.write_text(f"{os.getpid()},{server_pid}", encoding="utf-8")
    return pid_path


def stop_server(pid: int) -> None:
    if pid <= 0 or not process_is_running(pid):
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        os.kill(pid, signal.SIGTERM)


def run_tray(server_pid: int) -> int:
    pid_path = claim_single_instance(server_pid)
    if pid_path is None:
        return 0

    image = Image.open(ICON_PATH).convert("RGBA")

    def open_dashboard(_icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        webbrowser.open(APP_URL)

    def quit_app(icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        threading.Thread(target=stop_server, args=(server_pid,), daemon=True).start()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Åbn RosterMate", open_dashboard, default=True),
        pystray.MenuItem("Afslut RosterMate", quit_app),
    )
    icon = pystray.Icon("RosterMate", image, "RosterMate", menu)

    def watch_server() -> None:
        if server_pid <= 0:
            return
        while process_is_running(server_pid):
            time.sleep(1)
        icon.stop()

    threading.Thread(target=watch_server, daemon=True).start()
    try:
        icon.run()
    finally:
        try:
            if pid_path.read_text(encoding="utf-8").strip().split(",", 1)[0] == str(os.getpid()):
                pid_path.unlink(missing_ok=True)
        except OSError:
            pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-pid", type=int, default=0)
    args = parser.parse_args()
    return run_tray(args.server_pid)


if __name__ == "__main__":
    raise SystemExit(main())
