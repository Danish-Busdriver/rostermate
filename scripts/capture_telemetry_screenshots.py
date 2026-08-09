from __future__ import annotations

import tempfile
import threading
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

import app as app_module
from telemetry import TelemetryClient


def main() -> None:
    output_dir = Path(__file__).resolve().parents[1] / "assets" / "screenshots"
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rostermate-screenshots-") as temporary:
        root = Path(temporary)
        app_module.BASE_DIR = Path(__file__).resolve().parents[1]
        app_module.DATA_DIR = root / "data"
        app_module.BACKUP_DIR = root / "backups"
        app_module.OUTPUT_DIR = root / "output"
        app_module.save_driver_settings("1234", {"wizard_completed": True})
        original_admin_configured = TelemetryClient.admin_configured
        original_fetch_stats = TelemetryClient.fetch_stats
        TelemetryClient.admin_configured = lambda self: True
        TelemetryClient.fetch_stats = lambda self: {
            "total": 184,
            "active_7_days": 81,
            "active_30_days": 126,
            "active_90_days": 159,
            "new_7_days": 14,
            "new_30_days": 38,
            "platforms": [{"platform": "windows", "count": 73}, {"platform": "macos", "count": 53}],
            "versions": [{"version": app_module.APP_VERSION, "count": 97}, {"version": "1.13.0", "count": 29}],
            "activity": [
                {
                    "date": (date.today() - timedelta(days=29 - day)).isoformat(),
                    "installations": 35 + ((day * 11) % 58),
                    "syncs": 40 + ((day * 13) % 75),
                }
                for day in range(30)
            ],
        }
        server = make_server("127.0.0.1", 8766, app_module.app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1050}, device_scale_factor=1)
                page.goto("http://127.0.0.1:8766/1234/settings-page", wait_until="networkidle")
                page.screenshot(path=str(output_dir / "settings.png"), full_page=True)
                page.goto("http://127.0.0.1:8766/1234/admin", wait_until="networkidle")
                page.screenshot(path=str(output_dir / "admin.png"), full_page=True)
                browser.close()
        finally:
            server.shutdown()
            TelemetryClient.admin_configured = original_admin_configured
            TelemetryClient.fetch_stats = original_fetch_stats


if __name__ == "__main__":
    main()
