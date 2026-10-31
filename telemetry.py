from __future__ import annotations

import json
import os
import platform
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


USER_AGENT_TEMPLATE = "RosterMate-Telemetry/{version} (+https://github.com/Danish-Busdriver/rostermate)"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def load_runtime_config(base_dir: Path) -> dict[str, str]:
    config: dict[str, str] = {}
    try:
        from telemetry_runtime_config import TELEMETRY_CONFIG  # type: ignore

        if isinstance(TELEMETRY_CONFIG, dict):
            config.update({str(key): str(value) for key, value in TELEMETRY_CONFIG.items()})
    except (ImportError, TypeError, ValueError):
        pass
    local_path = base_dir / "telemetry-config.json"
    if local_path.exists():
        try:
            loaded = json.loads(local_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                config.update({str(key): str(value) for key, value in loaded.items()})
        except (OSError, json.JSONDecodeError):
            pass
    aliases = {
        "heartbeat_url": "ROSTERMATE_TELEMETRY_URL",
        "ingest_key": "ROSTERMATE_TELEMETRY_KEY",
        "stats_url": "ROSTERMATE_TELEMETRY_ADMIN_URL",
        "admin_key": "ROSTERMATE_TELEMETRY_ADMIN_KEY",
    }
    for key, env_name in aliases.items():
        if os.environ.get(env_name, "").strip():
            config[key] = os.environ[env_name].strip()
    return config


class TelemetryClient:
    def __init__(self, storage_root: Path, base_dir: Path, version: str) -> None:
        self.state_path = storage_root / "telemetry.json"
        self.base_dir = base_dir
        self.version = version
        self._lock = threading.Lock()

    def load_state(self) -> dict[str, Any]:
        try:
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                loaded.setdefault("enabled", True)
                return loaded
        except (OSError, json.JSONDecodeError):
            pass
        return {"enabled": True}

    def save_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        with self._lock:
            state = self.load_state()
            state["enabled"] = bool(enabled)
            if enabled and not state.get("installation_id"):
                state["installation_id"] = str(uuid.uuid4())
            self.save_state(state)
            return state

    def reset_identity(self) -> dict[str, Any]:
        with self._lock:
            state = self.load_state()
            state["installation_id"] = str(uuid.uuid4())
            state.pop("last_success_at", None)
            state.pop("last_attempt_at", None)
            self.save_state(state)
            return state

    def configured(self) -> bool:
        config = load_runtime_config(self.base_dir)
        return bool(config.get("heartbeat_url") and config.get("ingest_key"))

    def admin_configured(self) -> bool:
        config = load_runtime_config(self.base_dir)
        return bool(config.get("stats_url") and config.get("admin_key"))

    def _platform_name(self) -> str:
        if platform.system() == "Windows":
            return "windows"
        if platform.system() == "Darwin":
            return "macos"
        return "other"

    def send_heartbeat(self, now: datetime | None = None) -> bool:
        current = now or _utc_now()
        with self._lock:
            state = self.load_state()
            if not state.get("enabled"):
                return False
            config = load_runtime_config(self.base_dir)
            url = config.get("heartbeat_url", "")
            key = config.get("ingest_key", "")
            if not url.startswith("https://") or not key:
                return False
            installation_id = str(state.get("installation_id") or uuid.uuid4())
            state["installation_id"] = installation_id
            state["last_attempt_at"] = current.isoformat()
            self.save_state(state)
        try:
            response = requests.post(
                url,
                json={
                    "installation_id": installation_id,
                    "version": self.version,
                    "platform": self._platform_name(),
                },
                headers={
                    "X-RosterMate-Key": key,
                    "User-Agent": USER_AGENT_TEMPLATE.format(version=self.version),
                },
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException:
            return False
        with self._lock:
            state = self.load_state()
            state["last_success_at"] = current.isoformat()
            self.save_state(state)
        return True

    def fetch_stats(self) -> dict[str, Any]:
        config = load_runtime_config(self.base_dir)
        url = config.get("stats_url", "")
        key = config.get("admin_key", "")
        if not url.startswith("https://") or not key:
            raise RuntimeError("Adminadgang til telemetri er ikke konfigureret lokalt.")
        response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {key}",
                "User-Agent": USER_AGENT_TEMPLATE.format(version=self.version),
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Telemetri-serveren returnerede et ugyldigt svar.")
        return payload
