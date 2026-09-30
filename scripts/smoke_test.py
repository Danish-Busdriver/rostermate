from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_health(port: int, process: subprocess.Popen[bytes], timeout: float = 15) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"RosterMate stoppede med exit code {process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                payload = json.load(response)
            if isinstance(payload, dict):
                return payload
        except (OSError, json.JSONDecodeError):
            time.sleep(0.1)
    raise TimeoutError("RosterMate svarede ikke på /health inden for 15 sekunder")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="rostermate-smoke-") as storage:
        environment = {
            **os.environ,
            "ROSTERMATE_HOME": storage,
            "ROSTERMATE_PORT": str(port),
            "ROSTERMATE_HOST": "127.0.0.1",
        }
        process = subprocess.Popen(
            [sys.executable, str(root / "app.py")],
            cwd=root,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            payload = wait_for_health(port, process)
            if payload.get("status") != "ok":
                raise RuntimeError(f"Uventet health-svar: {payload}")
            print(f"RosterMate smoke test OK: port={port}, version={payload.get('version')}")
            return 0
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
